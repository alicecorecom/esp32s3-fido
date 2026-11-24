# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""Update the esp32s3-fido firmware over USB (CCID, no admin rights needed).

    uv run --no-project --with pyscard python -I tools/fwupdate.py info
    uv run --no-project --with pyscard python -I tools/fwupdate.py update build/devsb/signed/pico_fido.bin
    uv run --no-project --with pyscard python -I tools/fwupdate.py reboot
    uv run --no-project --with pyscard python -I tools/fwupdate.py image pico_fido.bin   # no key needed
    uv run --no-project --with pyscard python -I tools/fwupdate.py led-order rgb         # LED colour order

`update` writes the image into the other OTA slot (press BOOT or touch the
pad when the LED blinks blue), lets the key check it (signature and secure
version on a Secure Boot board), makes it the next boot slot and reboots.
The new firmware confirms itself once USB is up; if it never gets there, the
next reset goes back to the previous firmware.
"""
import argparse
import struct
import sys
import time

from smartcard.System import readers

AID = [0xF0] + list(b"espfido")
LED_ORDERS = ["rgb", "rbg", "grb", "gbr", "brg", "bgr"]   # PHY_LED_ORDER_* 0..5
CHUNK = 240                     # short APDUs: data <= 255 bytes incl. the 4-byte offset
STATES = {0: "new", 1: "pending verify", 2: "valid", 3: "invalid", 4: "aborted", 0xFFFFFFFF: "undefined", 0xFF: "unknown"}
SW_TEXT = {
    0x6982: "user presence not confirmed (timeout or cancelled)",
    0x6984: "image rejected (bad header, signature or secure version)",
    0x6A80: "out-of-order write",
    0x6A82: "no OTA slot to write",
    0x6A84: "image larger than the slot",
    0x6985: "no update in progress",
}


class KeyError_(Exception):
    pass


def find_key(name_filter):
    found = []
    for r in readers():
        if name_filter and name_filter.lower() not in str(r).lower():
            continue
        try:
            c = r.createConnection()
            c.connect()
        except Exception:
            continue
        _, sw1, sw2 = c.transmit([0x00, 0xA4, 0x04, 0x00, len(AID)] + AID)
        if (sw1, sw2) == (0x90, 0x00):
            found.append((r, c))
        else:
            c.disconnect()
    if not found:
        raise KeyError_("no esp32s3-fido key with the update applet found")
    if len(found) > 1:
        raise KeyError_("several keys found, pick one with --reader: " + ", ".join(str(r) for r, _ in found))
    return found[0][1]


def cmd(c, ins, data=b"", le=None):
    apdu = [0x80, ins, 0x00, 0x00]
    if data:
        apdu += [len(data)] + list(data)
    if le is not None:
        apdu += [le]
    resp, sw1, sw2 = c.transmit(apdu)
    sw = (sw1 << 8) | sw2
    if sw != 0x9000:
        raise KeyError_(f"INS {ins:02X}: SW {sw:04X} {SW_TEXT.get(sw, '')}".rstrip())
    return bytes(resp)


def info(c):
    b = cmd(c, 0x01, le=0)
    fmt, slot, state, flags = b[0], b[1], b[2], b[3]
    if fmt != 1:
        raise KeyError_(f"unknown INFO format {fmt}")
    app_sv, efuse_sv, slot_size = struct.unpack(">III", b[4:16])
    s = lambda o, n: b[o:o + n].split(b"\0")[0].decode(errors="replace")
    return {
        "slot": slot, "state": state, "flags": flags,
        "app_secure_version": app_sv, "efuse_secure_version": efuse_sv, "slot_size": slot_size,
        "version": s(16, 32), "project": s(48, 32), "date": s(80, 16), "time": s(96, 16),
        "idf": s(112, 32), "elf_sha256": b[144:176].hex(),
        "led_order": b[176] if len(b) > 176 else None,   # older firmware: not reported
    }


def print_info(i):
    f = i["flags"]
    print(f"running slot     : ota_{i['slot']} ({STATES.get(i['state'], i['state'])})")
    print(f"firmware         : {i['project']} {i['version']} (built {i['date']} {i['time']}, ESP-IDF {i['idf']})")
    print(f"ELF SHA-256      : {i['elf_sha256']}")
    print(f"secure version   : app {i['app_secure_version']}, eFuse {i['efuse_secure_version']}")
    print(f"secure boot      : {'on' if f & 1 else 'off'}")
    print(f"flash encryption : {('release' if f & 4 else 'development') if f & 2 else 'off'}")
    if i["led_order"] is not None:
        lo = i["led_order"]
        print(f"LED order        : {'default (grb)' if lo == 0xFF else LED_ORDERS[lo] if lo < 6 else lo}")
    if f & 8:
        print("update in progress")


def image_desc(img):
    """esp_app_desc_t at the start of the first segment (after the 24-byte
    image header and the 8-byte segment header)."""
    d = img[0x20:0x20 + 256]
    if len(d) < 176 or struct.unpack("<I", d[0:4])[0] != 0xABCD5432:
        raise KeyError_("no app description in the image (not an ESP-IDF app?)")
    s = lambda o, n: d[o:o + n].split(b"\0")[0].decode(errors="replace")
    return {"secure_version": struct.unpack("<I", d[4:8])[0], "version": s(16, 32),
            "project": s(48, 32), "elf_sha256": d[144:176].hex()}


def key_profile(i):
    """The image profile tag (idf.ps1 / ci/build.sh) that fits the key's state."""
    f = i["flags"]
    if f & 4:
        return "rel"
    if f & 2:
        return "sb" if f & 1 else "enc"
    return "dev"


def check_image(img, i, d):
    if len(img) < 0x1000 or img[0] != 0xE9:
        raise KeyError_("not an ESP app image (magic 0xE9 missing)")
    if len(img) > i["slot_size"]:
        raise KeyError_(f"image ({len(img)} bytes) larger than the slot ({i['slot_size']})")
    if i["flags"] & 1:
        # Secure Boot V2 signature sector: last 4 KB, first block starts with 0xE7
        if len(img) % 0x1000 or img[-0x1000] != 0xE7:
            raise KeyError_("the key has Secure Boot on, but the image is not signed")
    want = key_profile(i)
    got = d["version"].rpartition("+")[2] if "+" in d["version"] else None
    if got != want:
        # e.g. a +rel app switches a devsb board to RELEASE on its first boot
        raise KeyError_(f"image is for '+{got}' keys, this key needs '+{want}' (version {d['version']!r})")
    if d["secure_version"] < i["efuse_secure_version"]:
        raise KeyError_(f"image secure version {d['secure_version']} is below the key's {i['efuse_secure_version']}")


def update(c, path, reboot, local_check=True):
    img = open(path, "rb").read()
    i = info(c)
    print_info(i)
    d = image_desc(img) if len(img) > 0x120 else {"version": "?", "secure_version": 0, "project": "?", "elf_sha256": "?"}
    print(f"\nimage: {path} ({len(img)} bytes)")
    print(f"  {d['project']} {d['version']}, secure version {d['secure_version']}, ELF SHA-256 {d['elf_sha256']}")
    if local_check:
        check_image(img, i, d)
    print("press BOOT or touch the pad (LED blinks blue) ...")
    cmd(c, 0x10, struct.pack(">I", len(img)))
    t0 = time.time()
    try:
        for off in range(0, len(img), CHUNK):
            cmd(c, 0x11, struct.pack(">I", off) + img[off:off + CHUNK])
            done = min(off + CHUNK, len(img))
            if done == len(img) or (off // CHUNK) % 64 == 0:
                print(f"\r  {done * 100 // len(img):3d}% ({done}/{len(img)})", end="", flush=True)
        print(f"\nwritten in {time.time() - t0:.1f} s, checking ...")
        cmd(c, 0x12)
    except Exception:
        try:
            cmd(c, 0x13)
        except Exception:
            pass
        raise
    print("accepted: it boots from the other slot after the next reset")
    if reboot:
        cmd(c, 0x14)
        print("rebooting; check with `info` after the key is back")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reader", help="part of the smart card reader name, if several keys are plugged in")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("info")
    u = sub.add_parser("update")
    u.add_argument("image", help="app image (signed pico_fido.bin on a Secure Boot key)")
    u.add_argument("--no-reboot", action="store_true")
    u.add_argument("--skip-local-check", action="store_true", help=argparse.SUPPRESS)  # tests the key's own checks
    sub.add_parser("reboot")
    lo = sub.add_parser("led-order", help="set the LED colour order (press BOOT / touch)")
    lo.add_argument("order", choices=LED_ORDERS + ["default"],
                    help="grb (default) for boards whose red and green come out swapped with rgb; rgb for a standard WS2812")
    im = sub.add_parser("image", help="show the app description of an image file (no key needed)")
    im.add_argument("image")
    a = ap.parse_args()
    try:
        if a.action == "image":
            img = open(a.image, "rb").read()
            d = image_desc(img)
            signed = len(img) % 0x1000 == 0 and img[-0x1000] == 0xE7
            print(f"firmware       : {d['project']} {d['version']}")
            print(f"secure version : {d['secure_version']}")
            print(f"ELF SHA-256    : {d['elf_sha256']}")
            print(f"signed (SB V2) : {'yes' if signed else 'no'}")
            return
        c = find_key(a.reader)
        if a.action == "info":
            print_info(info(c))
        elif a.action == "led-order":
            p1 = 0xFF if a.order == "default" else LED_ORDERS.index(a.order)
            print("press BOOT or touch the pad (LED blinks blue) ...")
            resp, sw1, sw2 = c.transmit([0x80, 0x20, p1, 0x00])
            sw = (sw1 << 8) | sw2
            if sw == 0x6D00:
                raise KeyError_("this firmware has no LED order setting (v0.1.1 or later)")
            if sw != 0x9000:
                raise KeyError_(f"LED order: SW {sw:04X} {SW_TEXT.get(sw, '')}".rstrip())
            print(f"LED order set to {a.order}")
        elif a.action == "update":
            update(c, a.image, not a.no_reboot, not a.skip_local_check)
        else:
            cmd(c, 0x14)
    except KeyError_ as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
