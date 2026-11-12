"""Nuovo comando di avvio del QNAP TS-431P3 via console seriale (09/11/2026).
modo 'prova': definisce le variabili SOLO in RAM e prova la catena rete -> memoria interna (nessun saveenv).
modo 'salva': definisce le variabili, verifica che siano identiche, cambia bootcmd, saveenv, reset.
In ogni caso di dubbio: nessun saveenv e avvio manuale gia' collaudato dalla memoria interna."""
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
    for ch in (c + '\r').encode():          # lento: niente caratteri persi sulle righe lunghe
        os.write(fd, bytes([ch])); time.sleep(0.003)

def comando(c, attesa):
    global buf
    buf = b''
    scrivi(c); leggi(attesa)
    return buf.decode(errors='replace')

def righe(out):
    return [l.strip() for l in out.replace('\r', '').split('\n')]

def avvio_manuale(motivo):
    """Percorso collaudato alle 07:05: nessuna variabile nuova, nessun saveenv."""
    print(motivo + ' -> nessun saveenv, avvio manuale dalla memoria interna', flush=True)
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

print('AVANZAMENTO: attendo il conto alla rovescia', flush=True)
inizio = time.time()
while time.time() - inizio < 600:
    leggi(0.1)
    if b'hit any key' in buf.lower():
        for _ in range(600): os.write(fd, b' '); leggi(0.05)
        break
else:
    print('NESSUN CONTO ALLA ROVESCIA'); sys.exit(1)
print('AVANZAMENTO: autoboot fermato', flush=True)
comando('', 1)
env = comando('printenv', 6)
open(f'/tmp/uboot_env_prima_{MODO}.txt', 'w').write(env)
args = [l for l in righe(env) if l.startswith('bootargs=')]
if len(args) != 1 or 'mtdparts=' not in args[0]:
    avvio_manuale('bootargs QTS non trovati')
orig_args = args[0][len('bootargs='):]
r1 = righe(comando('echo uno && echo due', 2)); r2 = righe(comando('test 1 -eq 2 && echo NONO', 2))
if 'due' not in r1 or 'NONO' in r2:
    avvio_manuale('&& non funziona come previsto')
print('AVANZAMENTO: && funziona', flush=True)
errori = []
for n, v in VAR:
    comando(f"setenv {n} '{v}'", 1)
    if f'{n}={v}' not in righe(comando(f'printenv {n}', 2)):
        errori.append(n)
comando(f"setenv bootargs_qts '{orig_args}'", 1)
if f'bootargs_qts={orig_args}' not in righe(comando('printenv bootargs_qts', 2)):
    errori.append('bootargs_qts')
if errori:
    avvio_manuale('variabili non identiche: ' + ', '.join(errori))
print('AVANZAMENTO: variabili verificate', flush=True)
if MODO == 'prova':
    print('AVANZAMENTO: provo catena rete -> memoria interna (senza salvare)', flush=True)
    scrivi('run avvio_rete; run avvio_nand'); leggi(200)
elif MODO == 'salva':
    comando(f"setenv bootcmd '{NUOVO_BOOTCMD}'", 1)
    if f'bootcmd={NUOVO_BOOTCMD}' not in righe(comando('printenv bootcmd', 2)):
        avvio_manuale('bootcmd non identico')
    r = comando('saveenv', 25)
    print('AVANZAMENTO: saveenv -> ' + r.replace('\r', ' ').replace('\n', ' ')[-120:], flush=True)
    open('/tmp/uboot_env_dopo.txt', 'w').write(comando('printenv', 6))
    print('AVANZAMENTO: collaudo avvio di emergenza dalla rete (DHCP del router + server TFTP)', flush=True)
    scrivi('run avvio_rete; run avvio_nand'); leggi(260)
print('AVANZAMENTO: fine registrazione', flush=True)
