"""Prova di avvio Linux in RAM sul QNAP TS-431P3 via console seriale.
Ferma l'autoboot, imposta la rete SOLO in memoria (nessun saveenv), scarica i file via TFTP
e avvia con bootm. Non scrive nulla su NAND ne' sui dischi. Registra tutto in /tmp/nand_boot.txt."""
import os
import sys
import termios
import time

SERVER = '192.168.1.10'
IP_NAS = '192.168.1.130'
fd = os.open('/dev/ttyUSB0', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
a[4] = a[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, a)
log = open('/tmp/nand_boot.txt', 'wb')
buf = b''


def leggi(sec):
    global buf
    fine = time.time() + sec
    while time.time() < fine:
        try:
            d = os.read(fd, 4096)
            if d:
                log.write(d); log.flush(); buf += d
        except BlockingIOError:
            pass
        time.sleep(0.02)


def comando(c, attesa):
    global buf
    buf = b''
    os.write(fd, (c + '\r').encode())
    leggi(attesa)
    return buf


print('AVANZAMENTO: accendi il NAS, attendo il conto alla rovescia', flush=True)
inizio = time.time()
while time.time() - inizio < 600:
    leggi(0.1)
    if b'hit any key' in buf.lower():
        for _ in range(600):
            os.write(fd, b' '); leggi(0.05)
        break
else:
    print('NESSUN CONTO ALLA ROVESCIA'); sys.exit(1)
print('AVANZAMENTO: autoboot fermato', flush=True)
comando('', 1)
# Prova: kernel, DTB e initramfs letti dalla MEMORIA INTERNA (boot1_kernel). Nessun saveenv.
for c, ok in (('nand read 0x5000000 0x0 0xC00000', b'OK'), ('nand read 0x4000000 0xC00000 0x20000', b'OK'), ('nand read 0x4500000 0xE00000 0x240000', b'OK')):
    r = comando(c, 30)
    if ok not in r:
        print('LETTURA NAND FALLITA: ' + c, flush=True); sys.exit(4)
    print('AVANZAMENTO: ' + c, flush=True)
comando('setenv bootargs console=ttyS0,115200 rdinit=/init rootmd', 1)
print('AVANZAMENTO: avvio Linux dalla memoria interna', flush=True)
os.write(fd, b'bootm 0x5000000 0x4500000 0x4000000')
leggi(150)
print('AVANZAMENTO: fine registrazione', flush=True)
