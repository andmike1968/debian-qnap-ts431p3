#!/bin/sh
# Carica il driver USB (al_ext_pcie) a ogni avvio, con due protezioni (10/11/2026):
# 1) se il caricamento precedente non e arrivato in fondo (file segnale presente), NON riprova;
# 2) durante il caricamento il watchdog hardware e attivo: se il kernel si blocca, il NAS si riavvia.
F=/var/lib/al-usb-in-corso
if [ -f $F ]; then echo "USB: caricamento precedente non concluso, salto" | systemd-cat -t avvia-usb; exit 0; fi
touch $F; sync
/usr/local/sbin/nutri_wd.py & W=$!
sleep 1
modprobe al_ext_pcie; rc=$?
sleep 5
kill $W; wait $W 2>/dev/null
rm -f $F; sync
echo "USB: modprobe rc=$rc" | systemd-cat -t avvia-usb
