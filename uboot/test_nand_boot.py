"""One-shot test boot of Debian from NAND (boot1_kernel) on the QNAP TS-431P3 over the serial console.
Stops autoboot, reads kernel, DTB and initramfs from NAND and boots with bootm.
No saveenv, nothing is written. Full log in /tmp/nand_boot.txt."""
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


def read_serial(sec):
    global buf
    end = time.time() + sec
    while time.time() < end:
        try:
            d = os.read(fd, 4096)
            if d:
                log.write(d); log.flush(); buf += d
        except BlockingIOError:
            pass
        time.sleep(0.02)


def command(c, wait):
    global buf
    buf = b''
    os.write(fd, (c + '\r').encode())
    read_serial(wait)
    return buf


print('== power the NAS on, waiting for the U-Boot countdown', flush=True)
start = time.time()
while time.time() - start < 600:
    read_serial(0.1)
    if b'hit any key' in buf.lower():
        for _ in range(600):
            os.write(fd, b' '); read_serial(0.05)
        break
else:
    print('NO COUNTDOWN SEEN'); sys.exit(1)
print('== autoboot stopped', flush=True)
command('', 1)
# kernel, DTB and initramfs read from NAND (boot1_kernel). No saveenv.
for c, ok in (('nand read 0x5000000 0x0 0xC00000', b'OK'), ('nand read 0x4000000 0xC00000 0x20000', b'OK'), ('nand read 0x4500000 0xE00000 0x240000', b'OK')):
    r = command(c, 30)
    if ok not in r:
        print('NAND READ FAILED: ' + c, flush=True); sys.exit(4)
    print('== ' + c, flush=True)
command('setenv bootargs console=ttyS0,115200 rdinit=/init rootmd', 1)
print('== booting Linux from NAND', flush=True)
os.write(fd, b'bootm 0x5000000 0x4500000 0x4000000\r')
read_serial(150)
print('== end of log', flush=True)
