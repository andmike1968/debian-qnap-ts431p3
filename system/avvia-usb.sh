#!/bin/sh
# Loads the USB driver (al_ext_pcie) at every boot, with two safety nets:
# 1) if the previous load never finished (marker file still present), do NOT try again;
# 2) while loading, the hardware watchdog is armed: if the kernel hangs, the NAS reboots.
F=/var/lib/al-usb-in-corso
if [ -f $F ]; then echo "USB: previous load did not finish, skipping" | systemd-cat -t avvia-usb; exit 0; fi
touch $F; sync
/usr/local/sbin/nutri_wd.py & W=$!
sleep 1
modprobe al_ext_pcie; rc=$?
sleep 5
kill $W; wait $W 2>/dev/null
rm -f $F; sync
echo "USB: modprobe rc=$rc" | systemd-cat -t avvia-usb
