"""Sets the U-Boot boot chain of the QNAP TS-431P3 over the serial console (/dev/ttyUSB0).
Usage: python3 uboot_env.py test|save   (power the NAS on right after starting it)
  test: defines the variables in RAM ONLY and tries the chain network -> NAND (no saveenv).
  save: defines the variables, checks they are identical, changes bootcmd, saveenv.
On any doubt: no saveenv, and a plain manual boot from NAND.
Variable names (avvio_nand = boot from NAND, avvio_rete = boot from network, avvio_qts = boot QTS)
are kept as they are on the running system."""
import os, sys, termios, time
MODO = sys.argv[1]
fd = os.open('/dev/ttyUSB0', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
a[4] = a[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, a)
log = open(f'/tmp/uboot_{MODO}.txt', 'wb'); buf = b''

def leggi(sec):
    global buf
    fine = time.time() + sec
    while time.time() < fine:
        try:
            d = os.read(fd, 4096)
            if d: log.write(d); log.flush(); buf += d
        except BlockingIOError: pass
        time.sleep(0.02)

def scrivi(c):
    for ch in (c + '\r').encode():          # slow: no lost characters on long lines
        os.write(fd, bytes([ch])); time.sleep(0.003)

def comando(c, attesa):
    global buf
    buf = b''
    scrivi(c); leggi(attesa)
    return buf.decode(errors='replace')

def righe(out):
    return [l.strip() for l in out.replace('\r', '').split('\n')]

def avvio_manuale(motivo):
    """Known-good path: no new variables, no saveenv."""
    print(motivo + ' -> no saveenv, manual boot from NAND', flush=True)
    for c in ('nand read 0x5000000 0x0 0xC00000', 'nand read 0x4000000 0xC00000 0x20000', 'nand read 0x4500000 0xE00000 0x240000'):
        comando(c, 30)
    comando('setenv bootargs console=ttyS0,115200 rdinit=/init rootmd', 1)
    scrivi('bootm 0x5000000 0x4500000 0x4000000'); leggi(150)
    sys.exit(3)

VAR = [
    ('ipaddr', '192.168.1.130'),
    ('serverip', '192.168.1.10'),
    ('netmask', '255.255.255.0'),
    ('bootargs_deb', 'console=ttyS0,115200 rdinit=/init rootmd'),
    ('rete_par', 'setenv netretry no && setenv tftptimeout 2000 && setenv tftptimeoutcountmax 5'),
    ('rete_file', 'tftpboot 0x5000000 uImage && tftpboot 0x4000000 alpine-qnap-ts431p3.dtb && tftpboot 0x4500000 uInitrd'),
    ('nand_carica', 'nand read 0x5000000 0x0 0xC00000 && nand read 0x4000000 0xC00000 0x20000 && nand read 0x4500000 0xE00000 0x240000'),
    ('avvia_deb', 'setenv bootargs ${bootargs_deb} && bootm 0x5000000 0x4500000 0x4000000'),
    ('avvio_rete', 'run rete_par && setenv autoload no && dhcp && setenv serverip 192.168.1.10 && run rete_file && run avvia_deb'),
    ('forza_rete', '0'),
    ('avvio_nand', 'run nand_carica && run avvia_deb'),
    ('avvio_qts', 'setenv bootargs ${bootargs_qts}; nand read ${loadaddr} 0xF800000 0x2000000; run sata_cmd; run set_ddr_ro; bootm ${loadaddr} - ${fdtaddr}'),
    ('bootcmd_qts_originale', 'nand read $loadaddr 0 0x2000000;run sata_cmd;run set_ddr_ro;bootm $loadaddr - $fdtaddr;'),
]
NUOVO_BOOTCMD = 'if test "${forza_rete}" = 1; then run avvio_rete; fi; run avvio_nand; run avvio_rete; run avvio_qts'

print('== waiting for the U-Boot countdown', flush=True)
inizio = time.time()
while time.time() - inizio < 600:
    leggi(0.1)
    if b'hit any key' in buf.lower():
        for _ in range(600): os.write(fd, b' '); leggi(0.05)
        break
else:
    print('NO COUNTDOWN SEEN'); sys.exit(1)
print('== autoboot stopped', flush=True)
comando('', 1)
env = comando('printenv', 6)
open(f'/tmp/uboot_env_prima_{MODO}.txt', 'w').write(env)
args = [l for l in righe(env) if l.startswith('bootargs=')]
if len(args) != 1 or 'mtdparts=' not in args[0]:
    avvio_manuale('QTS bootargs not found')
orig_args = args[0][len('bootargs='):]
r1 = righe(comando('echo uno && echo due', 2)); r2 = righe(comando('test 1 -eq 2 && echo NONO', 2))
if 'due' not in r1 or 'NONO' in r2:
    avvio_manuale('&& does not work as expected')
print('== && works', flush=True)
errori = []
for n, v in VAR:
    comando(f"setenv {n} '{v}'", 1)
    if f'{n}={v}' not in righe(comando(f'printenv {n}', 2)):
        errori.append(n)
comando(f"setenv bootargs_qts '{orig_args}'", 1)
if f'bootargs_qts={orig_args}' not in righe(comando('printenv bootargs_qts', 2)):
    errori.append('bootargs_qts')
if errori:
    avvio_manuale('variables not identical: ' + ', '.join(errori))
print('== variables verified', flush=True)
if MODO == 'test':
    print('== trying chain network -> NAND (not saving)', flush=True)
    scrivi('run avvio_rete; run avvio_nand'); leggi(200)
elif MODO == 'save':
    comando(f"setenv bootcmd '{NUOVO_BOOTCMD}'", 1)
    if f'bootcmd={NUOVO_BOOTCMD}' not in righe(comando('printenv bootcmd', 2)):
        avvio_manuale('bootcmd not identical')
    r = comando('saveenv', 25)
    print('== saveenv -> ' + r.replace('\r', ' ').replace('\n', ' ')[-120:], flush=True)
    open('/tmp/uboot_env_dopo.txt', 'w').write(comando('printenv', 6))
    print('== testing emergency boot from the network (router DHCP + TFTP server)', flush=True)
    scrivi('run avvio_rete; run avvio_nand'); leggi(260)
print('== end of log', flush=True)
