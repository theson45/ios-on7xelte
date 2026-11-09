#!/usr/bin/env python3
"""Live XNU console from the phone over USB (patch 0127, boot-arg a5usb=2).

The kernel shows up as a CDC-ACM serial port, USB ID 1209:0002
("J7 Prime iOS kernel log"): on Windows 10/11 a "USB Serial Device (COMn)"
with the in-box driver, on Linux /dev/ttyACM*. It sends the whole console
from the start of the boot, then every new line as it is printed.

  on7xelte-usb-log.py [OUTDIR] [--port COM5]

Waits for the port, prints the log and appends it to
OUTDIR/usblog-<time>.txt (default: current directory). If the phone resets
or the cable is pulled it waits for the port again. Only reads; nothing is
sent to the phone. Needs no extra Python packages.
"""
import glob, os, sys, time

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
    first byte) instead of the COM default of waiting for the full count."""
    import ctypes, msvcrt
    from ctypes import wintypes

    class COMMTIMEOUTS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "ReadIntervalTimeout", "ReadTotalTimeoutMultiplier", "ReadTotalTimeoutConstant",
            "WriteTotalTimeoutMultiplier", "WriteTotalTimeoutConstant")]

    t = COMMTIMEOUTS(0xFFFFFFFF, 0xFFFFFFFF, 100, 0, 0)
    h = msvcrt.get_osfhandle(f.fileno())
    if not ctypes.windll.kernel32.SetCommTimeouts(wintypes.HANDLE(h), ctypes.byref(t)):
        print("SetCommTimeouts failed", ctypes.GetLastError(), flush=True)


def main():
    args = [a for a in sys.argv[1:]]
    port = None
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1]
        del args[i:i + 2]
    out = args[0] if args else "."
    os.makedirs(out, exist_ok=True)
    name = os.path.join(out, time.strftime("usblog-%Y%m%d-%H%M%S.txt"))
    log = open(name, "ab", buffering=0)
    print(f"log -> {name}", flush=True)
    while True:
        p = port or find_port()
        if not p:
            print(time.strftime("%H:%M:%S"), f"waiting for USB {VID}:{PID} (boot with a5usb=2)", flush=True)
            time.sleep(2)
            continue
        path = r"\\.\%s" % p if os.name == "nt" else p
        try:
            if os.name != "nt":
                os.system(f"stty -F {p} raw -echo 2>/dev/null")
            with open(path, "rb", buffering=0) as f:
                if os.name == "nt":
                    set_timeouts(f)
                print(f"--- {p} open ---", flush=True)
                while True:
                    b = f.read(16384)
                    if not b:
                        time.sleep(0.05)
                        continue
                    log.write(b)
                    sys.stdout.write(b.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
        except OSError as e:
            print(f"\n--- {p} closed ({e}) ---", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
