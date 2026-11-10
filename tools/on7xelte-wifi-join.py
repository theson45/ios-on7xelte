#!/usr/bin/env python3
"""on7xelte-wifi-join.py OUTDIR: ask for a Wi-Fi network name and password
(the password is not shown while typed) and hand them to the running
on7xelte-usb-log.py through OUTDIR/join.txt, which it sends once to the
phone as "wifi join SSIDHEX PASSHEX" and deletes. The logger, the kernel's
echo and its dvfs lines show only "wifi join (hidden)". An empty password
joins an open network. 0172 (on7xelte W5)."""
import getpass, os, sys

out = sys.argv[1] if len(sys.argv) > 1 else "."
ssid = input("Wi-Fi name (SSID): ").strip()
pw = getpass.getpass("Password (empty = open network): ")
if not ssid or len(ssid.encode()) > 32:
    sys.exit("SSID must be 1..32 bytes")
if pw and not 8 <= len(pw.encode()) <= 63:
    sys.exit("WPA2 password must be 8..63 characters")
line = "wifi join %s %s" % (ssid.encode().hex(), pw.encode().hex() if pw else "-")
tmp = os.path.join(out, "join.tmp")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(line + "\n")
os.replace(tmp, os.path.join(out, "join.txt"))
print("handed to the logger; watch the log for 'wifi: JOIN' lines")
