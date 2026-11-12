"""Sets the U-Boot boot chain of the QNAP TS-431P3 over the serial console (/dev/ttyUSB0).
Usage: python3 uboot_env.py test|save   (power the NAS on right after starting it)
  test: defines the variables in RAM ONLY and tries the chain network -> NAND (no saveenv).
  save: defines the variables, checks they are identical, changes bootcmd, saveenv.
On any doubt: no saveenv, and a plain manual boot from NAND.
Variables: boot_nand = boot from NAND, boot_net = boot from network, boot_qts = boot QTS."""
import os, sys, termios, time
MODE = sys.argv[1]
fd = os.open('/dev/ttyUSB0', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
a[4] = a[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, a)
log = open(f'/tmp/uboot_{MODE}.txt', 'wb'); buf = b''

def read_serial(sec):
    global buf
    end = time.time() + sec
    while time.time() < end:
        try:
            d = os.read(fd, 4096)
            if d: log.write(d); log.flush(); buf += d
        except BlockingIOError: pass
        time.sleep(0.02)

def send(c):
    for ch in (c + '\r').encode():          # slow: no lost characters on long lines
        os.write(fd, bytes([ch])); time.sleep(0.003)

def command(c, wait):
    global buf
    buf = b''
    send(c); read_serial(wait)
    return buf.decode(errors='replace')

def lines(out):
    return [l.strip() for l in out.replace('\r', '').split('\n')]

def manual_boot(reason):
    """Known-good path: no new variables, no saveenv."""
    print(reason + ' -> no saveenv, manual boot from NAND', flush=True)
    for c in ('nand read 0x5000000 0x0 0xC00000', 'nand read 0x4000000 0xC00000 0x20000', 'nand read 0x4500000 0xE00000 0x240000'):
        command(c, 30)
    command('setenv bootargs console=ttyS0,115200 rdinit=/init rootmd', 1)
    send('bootm 0x5000000 0x4500000 0x4000000'); read_serial(150)
    sys.exit(3)

VAR = [
    ('ipaddr', '192.168.1.130'),
    ('serverip', '192.168.1.10'),
    ('netmask', '255.255.255.0'),
    ('bootargs_deb', 'console=ttyS0,115200 rdinit=/init rootmd'),
    ('net_params', 'setenv netretry no && setenv tftptimeout 2000 && setenv tftptimeoutcountmax 5'),
    ('net_files', 'tftpboot 0x5000000 uImage && tftpboot 0x4000000 alpine-qnap-ts431p3.dtb && tftpboot 0x4500000 uInitrd'),
    ('nand_load', 'nand read 0x5000000 0x0 0xC00000 && nand read 0x4000000 0xC00000 0x20000 && nand read 0x4500000 0xE00000 0x240000'),
    ('boot_debian', 'setenv bootargs ${bootargs_deb} && bootm 0x5000000 0x4500000 0x4000000'),
    ('boot_net', 'run net_params && setenv autoload no && dhcp && setenv serverip 192.168.1.10 && run net_files && run boot_debian'),
    ('force_net', '0'),
    ('boot_nand', 'run nand_load && run boot_debian'),
    ('boot_qts', 'setenv bootargs ${bootargs_qts}; nand read ${loadaddr} 0xF800000 0x2000000; run sata_cmd; run set_ddr_ro; bootm ${loadaddr} - ${fdtaddr}'),
    ('bootcmd_qts_orig', 'nand read $loadaddr 0 0x2000000;run sata_cmd;run set_ddr_ro;bootm $loadaddr - $fdtaddr;'),
]
NEW_BOOTCMD = 'if test "${force_net}" = 1; then run boot_net; fi; run boot_nand; run boot_net; run boot_qts'

print('== waiting for the U-Boot countdown', flush=True)
start = time.time()
while time.time() - start < 600:
    read_serial(0.1)
    if b'hit any key' in buf.lower():
        for _ in range(600): os.write(fd, b' '); read_serial(0.05)
        break
else:
    print('NO COUNTDOWN SEEN'); sys.exit(1)
print('== autoboot stopped', flush=True)
command('', 1)
env = command('printenv', 6)
open(f'/tmp/uboot_env_prima_{MODE}.txt', 'w').write(env)
args = [l for l in lines(env) if l.startswith('bootargs=')]
if len(args) != 1 or 'mtdparts=' not in args[0]:
    manual_boot('QTS bootargs not found')
orig_args = args[0][len('bootargs='):]
r1 = lines(command('echo uno && echo due', 2)); r2 = lines(command('test 1 -eq 2 && echo NONO', 2))
if 'due' not in r1 or 'NONO' in r2:
    manual_boot('&& does not work as expected')
print('== && works', flush=True)
errors = []
for n, v in VAR:
    command(f"setenv {n} '{v}'", 1)
    if f'{n}={v}' not in lines(command(f'printenv {n}', 2)):
        errors.append(n)
command(f"setenv bootargs_qts '{orig_args}'", 1)
if f'bootargs_qts={orig_args}' not in lines(command('printenv bootargs_qts', 2)):
    errors.append('bootargs_qts')
if errors:
    manual_boot('variables not identical: ' + ', '.join(errors))
print('== variables verified', flush=True)
if MODE == 'test':
    print('== trying chain network -> NAND (not saving)', flush=True)
    send('run boot_net; run boot_nand'); read_serial(200)
elif MODE == 'save':
    command(f"setenv bootcmd '{NEW_BOOTCMD}'", 1)
    if f'bootcmd={NEW_BOOTCMD}' not in lines(command('printenv bootcmd', 2)):
        manual_boot('bootcmd not identical')
    r = command('saveenv', 25)
    print('== saveenv -> ' + r.replace('\r', ' ').replace('\n', ' ')[-120:], flush=True)
    open('/tmp/uboot_env_dopo.txt', 'w').write(command('printenv', 6))
    print('== testing emergency boot from the network (router DHCP + TFTP server)', flush=True)
    send('run boot_net; run boot_nand'); read_serial(260)
print('== end of log', flush=True)
