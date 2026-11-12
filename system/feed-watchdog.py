#!/usr/bin/python3
# Feeds the hardware watchdog while the USB driver loads. If the kernel hangs, feeding stops and the NAS reboots.
# On SIGTERM it writes the magic character V and disarms the watchdog.
import fcntl, os, signal, struct, sys, time
fd = os.open("/dev/watchdog0", os.O_WRONLY)
try: fcntl.ioctl(fd, 0xc0045706, struct.pack("i", 60))  # WDIOC_SETTIMEOUT 60 s
except OSError as e: print("settimeout", e)
def stop(*a):
    os.write(fd, b"V"); os.close(fd); sys.exit(0)
signal.signal(signal.SIGTERM, stop)
while True:
    os.write(fd, b"."); time.sleep(5)
