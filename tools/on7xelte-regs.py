#!/usr/bin/env python3
"""Run register sequences on the J7 Prime over the USB command channel (0133 "reg").

  on7xelte-regs.py LOGDIR SCRIPT        run a script file
  on7xelte-regs.py LOGDIR -e "OPS"      run one line of ops

LOGDIR is the folder of the running on7xelte-usb-log.py (it holds cmd.txt and
usblog-*.txt). Commands go into cmd.txt; answers are the "USB> " lines that
appear in the newest usblog file.

Script format, one op per line (see a5xelte_dvfs.c for the ops):

  # comment
  set I2C 0x10510000          name a number, use it as $I2C or $I2C+0x50
  r $I2C+0x50                 read
  w $I2C+0x44 0x30001         write
  m $I2C 0x80 0x80            read-modify-write
  p $I2C+0x24 0x80 0x80 5000  poll, 5 ms max
  d 100                       delay 100 us
  i 0 / i 1                   interrupts off / on
  ---                         send what is collected so far as one line
  !temp                       send any other command, print what it answers

Consecutive ops are sent together as one "reg" line (up to ~480 chars), so a
transfer runs without USB round trips in between. The run stops at the first
"reg: stopped" answer. The kernel refuses unsafe writes (eMMC, charger bus,
PMIC writes longer than one byte); this tool does not try to get around that.
"""
import glob
import os
import re
import sys
import time

MAX_LINE = 480


def newest_log(logdir):
    logs = glob.glob(os.path.join(logdir, 'usblog-*.txt'))
    if not logs:
        sys.exit(f'no usblog-*.txt in {logdir} (is on7xelte-usb-log.py running?)')
    return max(logs, key=os.path.getmtime)


def send(logdir, line, done_re, timeout):
    log = newest_log(logdir)
    start = os.path.getsize(log)
    with open(os.path.join(logdir, 'cmd.txt'), 'a', encoding='ascii') as f:
        f.write(line + '\n')
    print(f'>> {line}')
    t0 = time.time()
    buf = ''
    while time.time() - t0 < timeout:
        time.sleep(0.2)
        with open(log, 'rb') as f:
            f.seek(start)
            data = f.read().decode('utf-8', 'replace')
        new = data[len(buf):]
        buf = data
        for ln in new.splitlines():
            m = re.search(r'USB> (.*)', ln)
            if m and not m.group(1).startswith('$ '):
                print('   ' + m.group(1))
        if done_re and re.search(done_re, buf):
            return buf
    if done_re:
        print(f'   (no answer in {timeout} s: the phone may be frozen or busy)')
        return None
    return buf


def expand(line, names):
    def num(tok):
        def sym(m):
            if m.group(1) not in names:
                sys.exit(f'unknown name ${m.group(1)} in: {line}')
            return str(names[m.group(1)])
        tok = re.sub(r'\$(\w+)', sym, tok)
        if re.fullmatch(r'[0-9a-fA-Fx+\-]+', tok):
            return hex(eval(tok, {'__builtins__': {}}))   # digits, x, + and - only
        return tok
    parts = line.split()
    return ' '.join([parts[0]] + [num(p) for p in parts[1:]])


def run(logdir, lines):
    names = {}
    batch = []

    def flush():
        if not batch:
            return True
        out = send(logdir, 'reg ' + ' ; '.join(batch), r'USB> reg: (\d+ op\(s\) done|stopped at[^\n]*)', 20)
        batch.clear()
        return out is not None and 'reg: stopped' not in out

    for raw in lines:
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('set '):
            _, name, val = line.split(None, 2)
            names[name] = int(expand('x ' + val, names).split()[1], 16)
            continue
        if line == '---':
            if not flush():
                return 1
            continue
        if line.startswith('!'):
            if not flush():
                return 1
            send(logdir, line[1:], None, 4)
            continue
        op = expand(line, names)
        if op[0] not in 'rwmpdi':
            sys.exit(f'unknown op: {line}')
        if batch and len(' ; '.join(batch + [op])) > MAX_LINE:
            if not flush():
                return 1
        batch.append(op)
    return 0 if flush() else 1


def main():
    if len(sys.argv) == 4 and sys.argv[2] == '-e':
        sys.exit(run(sys.argv[1], sys.argv[3].split(';')))
    if len(sys.argv) == 3:
        with open(sys.argv[2], encoding='utf-8') as f:
            sys.exit(run(sys.argv[1], f.read().splitlines()))
    sys.exit(__doc__)


if __name__ == '__main__':
    main()
