#!/usr/bin/python3
# Nutre il watchdog hardware per la durata della prova USB. Se il kernel si blocca, smette e il NAS si riavvia.
# Alla fine (SIGTERM) scrive il carattere magico V e lo spegne.
import fcntl, os, signal, struct, sys, time
fd = os.open("/dev/watchdog0", os.O_WRONLY)
try: fcntl.ioctl(fd, 0xc0045706, struct.pack("i", 60))  # WDIOC_SETTIMEOUT 60 s
except OSError as e: print("settimeout", e)
def fine(*a):
    os.write(fd, b"V"); os.close(fd); sys.exit(0)
signal.signal(signal.SIGTERM, fine)
while True:
    os.write(fd, b"."); time.sleep(5)
