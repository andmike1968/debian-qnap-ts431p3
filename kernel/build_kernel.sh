#!/bin/bash
# Builds Linux 6.12 LTS + DTB + al_eth for the QNAP TS-431P3 (AL-314). Does not touch the NAS.
set -e
W=${W:-$HOME/nas-linux}; mkdir -p $W/out; cd $W
export ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf-
V=$(curl -s https://cdn.kernel.org/pub/linux/kernel/v6.x/ | grep -oE 'linux-6\.12\.[0-9]+\.tar\.xz' | sort -uV | tail -1)
echo "== downloading $V"
[ -f "$V" ] || curl -s -O https://cdn.kernel.org/pub/linux/kernel/v6.x/$V
D=${V%.tar.xz}; [ -d "$D" ] || tar xf $V; cd $D
A=arch/arm/boot/dts/amazon
grep -q interrupt-controller $A/alpine.dtsi || sed -i '/"al,alpine-msix"/a\			interrupt-controller;' $A/alpine.dtsi
grep -n -B2 -A3 'interrupt-controller;' $A/alpine.dtsi | grep -A3 -B2 msix | head -8
cp $W/ts431p3.dts $A/alpine-qnap-ts431p3.dts
grep -q ts431p3 $A/Makefile || echo 'dtb-$(CONFIG_ARCH_ALPINE) += alpine-qnap-ts431p3.dtb' >> $A/Makefile
make -s multi_v7_defconfig
cat $W/kernel-config.fragment > /tmp/frag; printf 'CONFIG_RTC_DRV_DS1307=y\nCONFIG_ARM_LPAE=n\n' >> /tmp/frag
scripts/kconfig/merge_config.sh -m .config /tmp/frag >/dev/null; make -s olddefconfig
echo "== building kernel $(date +%H:%M)"
make -s -j$(nproc) zImage modules 2>&1 | grep -iE "error" | head -20
make -s amazon/alpine-qnap-ts431p3.dtb
echo "== kernel built $(date +%H:%M)"
mkimage -A arm -O linux -T kernel -C none -a 0x00008000 -e 0x00008000 -d arch/arm/boot/zImage $W/out/uImage >/dev/null
cp $A/alpine-qnap-ts431p3.dtb $W/out/
cd $W; [ -d al_eth ] || git clone -q -b fix/mdio-c22-kernel-6.3 https://github.com/mornepousse/al_eth-standalone al_eth
echo "== building al_eth network driver"
make -C $W/$D M=$W/al_eth/src modules 2>&1 | grep -iE "error|warning: modpost" | head -10 || true
cp $W/al_eth/src/al_eth.ko $W/out/ 2>/dev/null || find $W/al_eth -name al_eth.ko -exec cp {} $W/out/ \;
echo "== RESULT ($D)"; ls -l $W/out
