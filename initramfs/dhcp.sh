#!/bin/sh
# udhcpc helper: assign the address obtained by DHCP to the interface
case "$1" in
  bound|renew)
    ip addr flush dev "$interface"
    ip addr add "$ip/${mask:-24}" dev "$interface"
    echo "$interface got $ip"
    ;;
esac
