# Installation guide — Debian 13 on QNAP TS-431P3

This is the procedure we actually followed. Read it all before starting.
Values to adapt to your network are written as `192.168.1.x` (NAS `192.168.1.130`, build/TFTP host `192.168.1.10`).

> **This erases QTS and all data on the disks.** Back up your data first.
> A serial console is required for the first part. Keep the original NAND dumps safe: they are your only way back.

## 0. What you need

- A **USB–serial adapter at 3.3 V** (never 5 V) on the `UART0_DEBUG` 4-pin header (JST PHR-4, 2 mm),
  115200 8N1. Connect only GND, RX, TX (RX/TX crossed). Measure the pins first: the two public pinouts disagree.
- A Linux **build host** (x86 is fine) with: `gcc-arm-linux-gnueabihf`, `make`, `bison`, `flex`, `libelf-dev`,
  `bc`, `u-boot-tools` (`mkimage`), `device-tree-compiler`, `debootstrap`, `qemu-user-static` + binfmt
  (to build an armhf rootfs on x86), `busybox-static` (armhf), a **TFTP server** and an **NFS server**.
- A terminal program (`picocom -b 115200 /dev/ttyUSB0`).

## 1. Build kernel, device tree and drivers

```sh
export W=$HOME/nas-linux
mkdir -p $W && cp kernel/dts/alpine-qnap-ts431p3.dts $W/ts431p3.dts && cp kernel/kernel-config.fragment $W/
bash kernel/build_kernel.sh          # downloads 6.12 LTS, builds zImage, DTB, uImage and al_eth
cd $W/linux-6.12.*
patch -p1 < .../kernel/patches/0001-aquantia-qnap-aqr112-id.patch
patch -p1 < .../kernel/patches/0002-ahci-qnap-sata-sw-leds.patch
cp .../kernel/config-6.12.116-ts431p3 .config && make ARCH=arm olddefconfig   # LPAE
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- -j$(nproc) zImage modules amazon/alpine-qnap-ts431p3.dtb
mkimage -A arm -O linux -T kernel -C none -a 0x00008000 -e 0x00008000 -d arch/arm/boot/zImage $W/out/uImage
```
Out-of-tree drivers (each is a normal kbuild module):
```sh
cd $W/al_eth && git checkout 2f0c081 && patch -p1 < .../drivers/al_eth/al_eth-wol-ratematch.patch
for d in al_eth/src  .../drivers/al_nand  .../drivers/al_thermal  .../drivers/al_ext_pcie; do
  make -C $W/linux-6.12.* ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- M=$d modules; done
```

## 2. Build the initramfs

The initramfs loads the network driver, assembles the RAID and switches to Debian on `md0`.
If `md0` is missing it drops to a shell on the serial console.

1. Open `initramfs/init` and write your two MAC addresses (printed on the NAS label, or read them from QTS):
   `eth0` = 2.5 GbE port, `eth1` = 1 GbE port.
2. Run:
```sh
cd initramfs
./build_initramfs.sh $W/al_eth/src/al_eth.ko mdadm.conf
```
The script downloads `busybox-static`, `mdadm` and the few libraries it needs straight from the Debian archive
(no cross-compiling), adds `init`, `dhcp.sh` and `al_eth.ko`, and writes `uInitrd`.
It needs only `curl`, `xz`, `dpkg-deb`, `cpio`, `gzip` and `mkimage`.

`mdadm.conf` describes your RAID arrays. For the very first boot (step 3) the RAID does not exist yet:
use an empty file (`touch mdadm.conf`). After step 5, on the NAS run `mdadm --detail --scan > mdadm.conf`,
copy it back and rebuild `uInitrd`.

Put `uImage`, `alpine-qnap-ts431p3.dtb` and `uInitrd` in the TFTP directory.

## 3. First boot over the network (nothing is written)

Stop U-Boot's countdown on the serial console, then:
```
setenv ipaddr 192.168.1.130; setenv serverip 192.168.1.10
tftpboot 0x5000000 uImage; tftpboot 0x4000000 alpine-qnap-ts431p3.dtb; tftpboot 0x4500000 uInitrd
setenv bootargs console=ttyS0,115200 rdinit=/init
bootm 0x5000000 0x4500000 0x4000000
```
Without `rootmd` on the command line the initramfs only runs in RAM and **does not touch the disks**.
(Note: on this board U-Boot overwrites `ipaddr`/`serverip` at power-on with 169.254.x.x; set them every time
or use `dhcp` and then `setenv serverip`.)

## 4. Back up the internal flash (mandatory)

From the RAM system: `insmod al_nand.ko modo_uboot=1`, then copy every partition **twice** and compare:
```sh
for i in 0 1 2 3 4 5 6; do dd if=/dev/mtd${i}ro of=/tmp/mtd$i.bin; md5sum /tmp/mtd$i.bin; done
```
Copy the files off the NAS. `modo_uboot=1` is required: without it the ECC layout does not match U-Boot
and reads/writes are wrong. Check `cat /sys/class/mtd/mtd*/bad_blocks` is 0 before writing anything.

## 5. Disks (destroys QTS data)

On each disk a new GPT: partition 1 = 20 GB, partition 2 = 4 GB, partition 3 = rest (all type Linux RAID).
```sh
mdadm --create /dev/md0 --level=1 --raid-devices=3 /dev/sd[abc]1   # system, ext4
mdadm --create /dev/md1 --level=1 --raid-devices=3 /dev/sd[abc]2   # swap
mdadm --create /dev/md2 --level=5 --raid-devices=3 /dev/sd[abc]3   # data, ext4
mkfs.ext4 /dev/md0; mkswap /dev/md1; mkfs.ext4 /dev/md2
```
After the initial sync: `mdadm --grow --bitmap=internal /dev/md2` (much faster resync after a crash).

## 6. Debian root filesystem

```sh
debootstrap --arch=armhf --include=openssh-server,mdadm,ifupdown,isc-dhcp-client,smartmontools trixie rootfs http://deb.debian.org/debian
```
Copy it to `md0` (mounted on the NAS from the RAM system, e.g. with rsync over the network), then inside:
- `/etc/fstab`: `md0` → `/`, `md1` swap, `md2` → `/srv/dati` (`nofail`);
- `/etc/mdadm/mdadm.conf`: `mdadm --detail --scan`;
- `/etc/network/interfaces`: see `system/interfaces` (bonding with failover; or a single port `enp0s1`);
- kernel modules in `/lib/modules/6.12.*/` (`modules_install`) plus `al_nand.ko`, `al_thermal.ko`,
  `al_ext_pcie.ko` in `extra/`, then `depmod -a`;
- hostname, root SSH key, a user with sudo.

Test it: boot over TFTP again as in step 3, adding `rootmd` to `bootargs`. Debian must start from the disks.

## 7. Write Debian into NAND `boot1_kernel` (mtd2)

Only when step 6 works. QTS stays in `boot2_kernel` (mtd4). From Debian (or the RAM system) with
`al_nand modo_uboot=1` loaded; erase blocks are 128 KiB:
```sh
flash_erase /dev/mtd2 0        96 && nandwrite -p -s 0        /dev/mtd2 uImage                  # 0x000000
flash_erase /dev/mtd2 0xC00000 1  && nandwrite -p -s 0xC00000 /dev/mtd2 alpine-qnap-ts431p3.dtb # 0xC00000
flash_erase /dev/mtd2 0xE00000 18 && nandwrite -p -s 0xE00000 /dev/mtd2 uInitrd                 # 0xE00000
```
**Read back and compare md5** of each piece (`head -c <size> /dev/mtd2ro`, `dd ... skip=`) before going on.
Then, from U-Boot, read them once by hand to be sure U-Boot sees the same data:
```
nand read 0x5000000 0x0 0xC00000; nand read 0x4000000 0xC00000 0x20000; nand read 0x4500000 0xE00000 0x240000
setenv bootargs console=ttyS0,115200 rdinit=/init rootmd; bootm 0x5000000 0x4500000 0x4000000
```

## 8. Make it permanent (U-Boot environment)

`uboot/uboot_env.py` sets these variables over the serial line (it has a test mode that changes RAM only;
`saveenv` writes the SPI flash — keep the `mtd1.bin` backup):
- `avvio_nand` — load the three pieces from NAND and boot Debian;
- `avvio_rete` — DHCP + TFTP from the build host (emergency boot);
- `avvio_qts` — original QTS from `boot2_kernel`;
- `bootcmd = run avvio_nand; run avvio_rete; run avvio_qts`.

Power-cycle and check Debian comes up by itself.

## 9. Extra hardware support (after first boot)

Copy the files in `system/`:

| File | Where | Purpose |
|---|---|---|
| `qnap-mcu-poweroff` | `/usr/lib/systemd/system-shutdown/` (chmod 755) | real power-off via MCU |
| `interfaces` | `/etc/network/interfaces` | bonding failover, Wake-on-LAN on `enp0s1` (needs `bonding.ko`) |
| `al_ext_pcie.conf` | `/etc/modprobe.d/` | USB driver option |
| `qnap-usb-load.sh`, `feed-watchdog.py` | `/usr/local/sbin/` | load USB driver at boot, guarded by the hardware watchdog |
| `qnap-usb.service` | `/etc/systemd/system/` (`systemctl enable qnap-usb`) | |
| `90-nas-memory.conf` | `/etc/sysctl.d/` | `vm.min_free_kbytes=65536` (network stability) |

Wake-on-LAN: `ethtool enp0s1` must show `Wake-on: g`; wake it with `wakeonlan <MAC of enp0s1>`.

Optional: Cockpit (`apt install cockpit cockpit-storaged cockpit-packagekit`), NFS (`nfs-kernel-server`
needs `nfsd.ko`, not in our minimal config: enable `CONFIG_NFSD=m`), Samba, `pcp` + `xz-utils` for metrics.

## Going back to QTS

From the U-Boot console: `run avvio_qts`. QTS will start as an uninitialised NAS (its system partitions on the
disks are gone). For a full restore write back your `mtd*.bin` dumps.
