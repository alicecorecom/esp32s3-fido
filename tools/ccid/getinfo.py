# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
# Ask the key for CTAP2 getInfo over CCID (no admin rights needed, unlike raw
# FIDO HID on Windows) and print the AAGUID.
#   uv run --no-project --with pyscard python -I tools/ccid/getinfo.py
from smartcard.System import readers
rs = readers(); print("readers:", rs)
for r in rs:
    try:
        c = r.createConnection(); c.connect()
    except Exception as e:
        print(r, "connect failed", e); continue
    aid = [0xA0,0x00,0x00,0x06,0x47,0x2F,0x00,0x01]
    d, sw1, sw2 = c.transmit([0x00,0xA4,0x04,0x00,len(aid)]+aid)
    print(r, "select", bytes(d), hex(sw1), hex(sw2))
    d, sw1, sw2 = c.transmit([0x80,0x10,0x00,0x00,0x01,0x04,0x00])
    while sw1 == 0x61:
        d2, sw1, sw2 = c.transmit([0x80,0xC0,0x00,0x00,sw2]); d += d2
    b = bytes(d); print("getInfo sw", hex(sw1), hex(sw2), "len", len(b))
    i = b.find(b"\x03\x50")
    if i >= 0:
        import uuid; print("AAGUID:", uuid.UUID(bytes=b[i+2:i+18]))
