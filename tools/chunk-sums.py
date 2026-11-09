#!/usr/bin/env python3
"""Print "INDEX SHA256" for every 128 MiB chunk of an image (the last one may be short).

The on7xelte root is written to USERDATA in these chunks, so the per-chunk
hashes tell which chunks differ between two images, or between an image and
the partition (`dd bs=1048576 skip=INDEX*128 count=128 | sha256sum` on the phone).

  chunk-sums.py IMAGE
"""
import hashlib, sys

CH = 128 << 20

with open(sys.argv[1], "rb") as f:
    i = 0
    while True:
        b = f.read(CH)
        if not b:
            break
        print(i, hashlib.sha256(b).hexdigest())
        i += 1
