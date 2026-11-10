#!/usr/bin/env python3
"""Live XNU console from the phone over USB, and kernel commands to it
(patches 0127/0128, boot-arg a5usb=2 log only, a5usb=3 log + commands).

The kernel shows up as a CDC-ACM serial port, USB ID 1209:0002
("J7 Prime iOS kernel log"): on Windows 10/11 a "USB Serial Device (COMn)"
with the in-box driver, on Linux /dev/ttyACM*. It sends the whole console
from the start of the boot, then every new line as it is printed.

  on7xelte-usb-log.py [OUTDIR] [--port COM5] [--no-replay]

Waits for the port, prints the log and appends it to OUTDIR/usblog-<time>.txt
and, with the PC time of each line, OUTDIR/usblog-<time>-ts.txt (default
OUTDIR: current directory). If the phone resets or the cable is pulled it
waits for the port again.

Commands (a5usb=3; with a5usb=2 the kernel drops them):
  - typed into this program's terminal, one per line, or
  - appended as lines to OUTDIR/cmd.txt by anything else (another shell,
    an agent): every new line is sent once.
  - OUTDIR/join.txt (0172, written by on7xelte-wifi-join.py): its line is
    sent once and the file deleted; the log shows "wifi join (hidden)".
Answers come back in the log as "USB> ..." lines. Kernel commands: help,
info, replay, ps, sample NAME[,NAME]|PID, kill PID [SIG], rd PA [N],
reboot, recovery (reboot into TWRP).

On every port open "replay" is sent first (unless --no-replay), so the start
of the boot that went out before the port was open is not lost (the log
then holds those lines twice), then "time EPOCH" with the PC's clock (0137:
the phone has no other source of real time; --no-time skips it). Needs no
extra Python packages.
"""
import glob, os, queue, sys, threading, time

VID, PID = "1209", "0002"


def find_port():
    if os.name == "nt":
        import winreg
        base = rf"SYSTEM\CurrentControlSet\Enum\USB\VID_{VID}&PID_{PID}"
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        except OSError:
            return None
        ports = []
        for i in range(winreg.QueryInfoKey(k)[0]):
            inst = winreg.EnumKey(k, i)
            try:
                p = winreg.OpenKey(k, inst + r"\Device Parameters")
                ports.append(winreg.QueryValueEx(p, "PortName")[0])
            except OSError:
                pass
        for name in ports:          # the one that opens is the attached one
            try:
                open(r"\\.\%s" % name, "rb", buffering=0).close()
                return name
            except OSError:
                continue
        return None
    for dev in sorted(glob.glob("/dev/ttyACM*")):
        sysdir = "/sys/class/tty/%s/device/.." % os.path.basename(dev)
        try:
            if open(sysdir + "/idVendor").read().strip() == VID and \
               open(sysdir + "/idProduct").read().strip() == PID:
                return dev
        except OSError:
            continue
    return None


def set_timeouts(f):
    """Return from a read with whatever arrived (wait at most 100 ms for the
    first byte) instead of the COM default of waiting for the full count;
    writes time out after 2 s."""
    import ctypes, msvcrt
    from ctypes import wintypes

    class COMMTIMEOUTS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "ReadIntervalTimeout", "ReadTotalTimeoutMultiplier", "ReadTotalTimeoutConstant",
            "WriteTotalTimeoutMultiplier", "WriteTotalTimeoutConstant")]

    t = COMMTIMEOUTS(0xFFFFFFFF, 0xFFFFFFFF, 100, 0, 2000)
    h = msvcrt.get_osfhandle(f.fileno())
    if not ctypes.windll.kernel32.SetCommTimeouts(wintypes.HANDLE(h), ctypes.byref(t)):
        print("SetCommTimeouts failed", ctypes.GetLastError(), flush=True)


def stdin_commands(q):
    for line in sys.stdin:
        if line.strip():
            q.put(line.strip())


def shown(c):
    """What the log may show of a command: never the Wi-Fi join arguments."""
    return "wifi join (hidden)" if c.startswith("wifi join") else c


def file_commands(path, q):
    """Send each line appended to path once (lines already there at start
    are skipped); a join.txt next to it is sent once and deleted."""
    open(path, "a").close()
    pos = os.path.getsize(path)
    rest = b""
    secret = os.path.join(os.path.dirname(path) or ".", "join.txt")
    while True:
        time.sleep(0.5)
        if os.path.exists(secret):
            try:
                with open(secret, "r", encoding="utf-8") as f:
                    line = f.read().strip()
                os.remove(secret)
                if line.startswith("wifi join "):
                    q.put(line)
            except OSError:
                pass
        try:
            size = os.path.getsize(path)
            if size < pos:              # truncated: start over
                pos = 0
            if size == pos:
                continue
            with open(path, "rb") as f:
                f.seek(pos)
                data = rest + f.read()
                pos = f.tell()
        except OSError:
            continue
        *lines, rest = data.split(b"\n")
        for line in lines:
            line = line.decode("utf-8", errors="replace").strip()
            if line:
                q.put(line)


def main():
    args = [a for a in sys.argv[1:]]
    port = None
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1]
        del args[i:i + 2]
    replay = "--no-replay" not in args
    settime = "--no-time" not in args
    args = [a for a in args if a not in ("--no-replay", "--no-time")]
    out = args[0] if args else "."
    os.makedirs(out, exist_ok=True)
    name = os.path.join(out, time.strftime("usblog-%Y%m%d-%H%M%S.txt"))
    log = open(name, "ab", buffering=0)
    # Same text with the PC arrival time of each line (the kernel sends
    # within ~1 ms of printing once the port is open): finds slow boot steps.
    ts = open(name[:-4] + "-ts.txt", "a", encoding="utf-8", buffering=1)
    t0 = time.time()
    pending = ""
    cmds = queue.Queue()
    cmdfile = os.path.join(out, "cmd.txt")
    threading.Thread(target=file_commands, args=(cmdfile, cmds), daemon=True).start()
    if sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=stdin_commands, args=(cmds,), daemon=True).start()
    print(f"log -> {name}\ncommands: type here or append lines to {cmdfile}", flush=True)

    def note(text):
        nonlocal pending
        stamp = "%s +%8.1fs " % (time.strftime("%H:%M:%S"), time.time() - t0)
        ts.write(stamp + "### " + text + "\n")
        print("###", text, flush=True)

    while True:
        p = port or find_port()
        if not p:
            print(time.strftime("%H:%M:%S"), f"waiting for USB {VID}:{PID} (boot with a5usb=2 or 3)", flush=True)
            time.sleep(2)
            continue
        path = r"\\.\%s" % p if os.name == "nt" else p
        try:
            if os.name != "nt":
                os.system(f"stty -F {p} raw -echo 2>/dev/null")
            with open(path, "r+b", buffering=0) as f:
                if os.name == "nt":
                    set_timeouts(f)
                note(f"{p} open")
                if replay:
                    cmds.put("replay")
                if settime:
                    cmds.put("time %d" % int(time.time()))
                while True:
                    while not cmds.empty():
                        c = cmds.get()
                        f.write((c + "\n").encode())
                        note(f"sent: {shown(c)}")
                    b = f.read(16384)
                    if not b:
                        time.sleep(0.05)
                        continue
                    log.write(b)
                    text = b.decode("utf-8", errors="replace")
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    pending += text
                    *lines, pending = pending.split("\n")
                    stamp = "%s +%8.1fs " % (time.strftime("%H:%M:%S"), time.time() - t0)
                    for line in lines:
                        ts.write(stamp + line + "\n")
        except OSError as e:
            note(f"{p} closed ({e})")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
