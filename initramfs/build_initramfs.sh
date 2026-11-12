#!/bin/bash
# Builds uInitrd for the QNAP TS-431P3 (Debian 13 armhf) on any Linux host with dpkg-deb and mkimage.
# Downloads busybox-static, mdadm and the libraries mdadm needs directly from the Debian archive.
# Usage: ./build_initramfs.sh <al_eth.ko> <mdadm.conf>
#   mdadm.conf: on the NAS, after creating the RAID arrays:  mdadm --detail --scan > mdadm.conf
set -e
ETH=${1:?path to al_eth.ko}; CONF=${2:?path to mdadm.conf}
HERE=$(cd "$(dirname "$0")" && pwd)
MIRROR=http://deb.debian.org/debian
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
echo "== Debian package index (trixie, armhf)"
curl -sf "$MIRROR/dists/trixie/main/binary-armhf/Packages.xz" | xz -d > "$W/Packages"
get() {  # download and unpack one package into $W/x
  f=$(awk -v p="$1" '$1=="Package:"{n=$2} $1=="Filename:" && n==p {print $2; exit}' "$W/Packages")
  [ -n "$f" ] || { echo "package $1 not found"; exit 1; }
  echo "   $1"; curl -sf -o "$W/p.deb" "$MIRROR/$f"; dpkg-deb -x "$W/p.deb" "$W/x"
}
for p in busybox-static mdadm libc6 libudev1 libcap2; do get $p; done
I=$W/ird; mkdir -p $I/{bin,sbin,dev,proc,sys,tmp,etc,newroot,lib/modules,usr/lib/arm-linux-gnueabihf}
cp $W/x/usr/bin/busybox $I/bin/busybox
cp $W/x/sbin/mdadm $I/sbin/mdadm 2>/dev/null || cp $W/x/usr/sbin/mdadm $I/sbin/mdadm
for l in ld-linux-armhf.so.3 libc.so.6 libudev.so.1 libcap.so.2; do
  s=$(find $W/x -name "$l*" \( -type f -o -type l \) | head -1); cp -L "$s" $I/usr/lib/arm-linux-gnueabihf/$l
done
cp -L $I/usr/lib/arm-linux-gnueabihf/ld-linux-armhf.so.3 $I/lib/ld-linux-armhf.so.3
cp "$ETH" $I/lib/modules/al_eth.ko
cp "$CONF" $I/etc/mdadm.conf
cp "$HERE/init" $I/init; cp "$HERE/dhcp.sh" $I/bin/dhcp.sh; chmod 755 $I/init $I/bin/dhcp.sh
(cd $I && find . | cpio -o -H newc --quiet | gzip -9) > "$W/initrd.gz"
mkimage -A arm -O linux -T ramdisk -C none -n "TS-431P3 initramfs" -d "$W/initrd.gz" uInitrd >/dev/null
echo "== uInitrd ready ($(stat -c %s uInitrd) bytes). Remember to set your MAC addresses in init."
