# Debian 13 on the QNAP TS-431P3 (Annapurna Labs Alpine AL-314)

Run a current, mainline-based **Debian 13 "trixie"** (Linux **6.12 LTS**) on the QNAP **TS-431P3**,
replacing QTS, with almost full hardware support and without losing the ability to go back to QTS.

This work started from [mornepousse/liberate_nas_qnap-ts431p](https://github.com/mornepousse/liberate_nas_qnap-ts431p)
(TS-431P, AL-212) and the [al_eth-standalone](https://github.com/mornepousse/al_eth-standalone) driver.
The TS-431P3 uses a different SoC (AL-314, quad Cortex-A15, 8 GB RAM) and different peripherals, so many
pieces had to be added or rewritten. Everything here was tested on real hardware.

> **Warning.** This writes to the internal NAND and the U-Boot environment. A mistake can leave the NAS
> unbootable without a serial console. Make full backups of all MTD partitions first. No warranty.

## What works

| Feature | Status | How |
|---|---|---|
| Boot Debian from internal NAND (`boot1_kernel`) | ✅ | U-Boot chain: NAND → network (DHCP+TFTP) → QTS kept in `boot2_kernel` |
| NAND read/write from Linux, U-Boot compatible | ✅ | `al_nand` with `modo_uboot=1` (BCH 4-bit, 512 B codewords, std OOB) |
| Root filesystem on RAID 1 (md), data on RAID 5 | ✅ | standard Debian / mdadm |
| 1 GbE port (AR8035) + **Wake-on-LAN** | ✅ | `al_eth` + minimal `ethtool` WoL ops |
| **2.5 GbE port** (Aquantia AQR112, QNAP PHY id `0x03a1b792`) | ✅ | PHY id added to `aquantia`, MAC kept in 10GBASE-R with PHY rate matching |
| Both ports as one IP with automatic failover | ✅ | bonding `active-backup` |
| **Real power-off** (not just halt) | ✅ | MCU on `/dev/ttyS1`: `@C0` + XOR checksum → `@C03`, systemd shutdown hook |
| **USB** (Etron EJ188 xHCI behind the external PCIe) | ✅ read/write, USB 2 and USB 3 | out-of-tree `al_ext_pcie` (MSI, MRRS 128 + Extended Tags off) |
| **HDD activity LEDs** (blink per disk) | ✅ | `ahci` patch reading QNAP `al-sata-sw-leds` node + GPIO controllers 2–4 in DTS |
| Temperature sensor | ✅ | `al_thermal` |
| Cockpit web UI, NFS, Samba | ✅ | Debian packages |

## Installation

Step-by-step guide: **[INSTALL.md](INSTALL.md)** — build, first network boot, NAND backup, disks,
Debian rootfs, writing to NAND, U-Boot boot chain, extra hardware, and how to go back to QTS.

## Hardware notes (TS-431P3)

- SoC Annapurna Labs **Alpine V1 AL-314**, 4× Cortex-A15, **8 GB** → kernel built with **LPAE** + HIGHMEM.
- 4 SATA bays on the second AHCI controller (`0000:00:09.0`), ports 0–3.
- Serial console: 4-pin `UART0_DEBUG`, 115200 8N1, 3.3 V.
- MCU (fan, power, buttons) on `/dev/ttyS1` at 115200 8N1.

## The non-obvious fixes (root causes)

These are the things that took the longest and that you will hit too:

1. **NAND ECC.** U-Boot/QTS use BCH 4-bit with **four 512-byte codewords** per 2 KB page (8 ECC bytes each,
   OOB offset 4–35). The stock driver assumed one 2048-byte codeword. With several codewords the MTD core
   also read the OOB in "syndrome" layout and reported ~200 false bad blocks: use `nand_read_oob_std` /
   `nand_write_oob_std`. See `drivers/al_nand`.
2. **2.5 GbE with no RX at 1 Gb/s.** The AQR112 talks **10GBASE-R (XFI)** to the MAC and does rate matching.
   `al_eth_adjust_link` switched the MAC to SGMII at 1 G → link up, nothing received. Keep the MAC in
   10G serial mode when `phydev->interface == PHY_INTERFACE_MODE_10GBASER`.
3. **USB writes failing with `TRB error` / endless resets while reads worked.** The Etron controller had
   **Max Read Request Size 512 B and Extended Tags on**, while the Alpine root port accepts **256 B and no
   Extended Tags**. Reads (device → memory) work, every DMA read of more than one small packet fails.
   Set MRRS 128 and clear `EXT_TAG` on the whole external domain **before** handing devices to drivers.
   (Not the cause, all verified: AXI snoop bits, CCU snoop, 32-bit DMA limit, transfer size.)
4. **USB INTx never reaches the CPU** → use **MSI** through the `al,alpine-msix` domain.
5. **HDD LEDs on but not blinking.** QTS drives them from `ahci.c` via GPIOs listed in an
   `annapurna-labs,al-sata-sw-leds` node; mainline has no such code and the DTS lacked GPIO controllers 2–4.
6. **Power-off only halts.** Systemd must send `@C03` to the MCU in a `system-shutdown` hook (only at the very end).
7. **Home network freezing under heavy copies.** With the default `vm.min_free_kbytes` (~3 MB) `al_eth`
   ran out of RX buffers (`failed to alloc buffer for rx queue`) during large rsync jobs.
   `vm.min_free_kbytes = 65536` fixed it in our tests.

## Known issues

- If the cable of the **1 GbE port is unplugged/replugged while running**, that port may stop receiving and
  transmit at line rate, flooding the LAN, until reboot. Root cause in `al_eth` not found yet.
- USB: UAS is not available (controller without streams), `usb-storage` is used. Tested with USB 2 disks,
  a USB 2 stick and a USB 3 disk (108 MB/s read).
- The `al_ext_pcie` module is a minimal port of QNAP's `pci-external-alpine.c`, not an upstreamable driver.

## Repository layout

```
kernel/
  build_kernel.sh               fetch + build 6.12 LTS, DTB, uImage (cross: arm-linux-gnueabihf)
  kernel-config.fragment        on top of multi_v7_defconfig
  config-6.12.116-ts431p3       full working .config
  dts/alpine-qnap-ts431p3.dts   device tree (SPI, serdes, thermal, I2C, GPIO 0-4, HDD LEDs)
  patches/0001-aquantia-qnap-aqr112-id.patch
  patches/0002-ahci-qnap-sata-sw-leds.patch
drivers/
  al_nand/      NAND driver, U-Boot compatible ECC (modo_uboot=1)
  al_eth/       patch for al_eth-standalone (branch fix/mdio-c22-kernel-6.3, 2f0c081): WoL, 2.5 GbE rate matching
  al_ext_pcie/  external PCIe / USB host bridge (from QNAP GPL sources)
  al_thermal/   SoC temperature sensor
system/         power-off hook, USB loader with watchdog guard, bonding config, sysctl
uboot/          scripts used over the serial console to set the boot chain
initramfs/init  init script of the initramfs (RAM test mode, or RAID root with `rootmd`)
```

## Boot layout in NAND (`boot1_kernel`, mtd2)

| Offset | Content |
|---|---|
| `0x000000` | uImage (kernel) |
| `0xC00000` | DTB |
| `0xE00000` | uInitrd (contains `al_eth`, `al_nand`) |

QTS stays untouched in `boot2_kernel` as last fallback.

## Credits and licenses

Built with help from [Claude Code](https://claude.ai/claude-code) (Anthropic).


- Base work: [mornepousse](https://github.com/mornepousse).
- Driver code derived from Annapurna Labs / QNAP GPL sources (QTS 5.2.3 kernel 4.2). The `al_hal_*`
  files are dual licensed (Annapurna Labs commercial license **or** GPL v2 / BSD); here they are distributed
  under GPL v2. Kernel patches are GPL v2.
- QTS firmware images are **not** included.
