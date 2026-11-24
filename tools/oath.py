# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""One-time passwords (OATH TOTP / HOTP) on an esp32s3-fido key.

    uv run --no-project --with yubikey-manager python -I tools/oath.py list
    uv run --no-project --with yubikey-manager python -I tools/oath.py code            # all TOTP codes
    uv run --no-project --with yubikey-manager python -I tools/oath.py code github     # one account
    uv run --no-project --with yubikey-manager python -I tools/oath.py add             # asks for an otpauth:// URI
    uv run --no-project --with yubikey-manager python -I tools/oath.py add --issuer GitHub --name me --touch
    uv run --no-project --with yubikey-manager python -I tools/oath.py rename github --issuer GitHub --name you
    uv run --no-project --with yubikey-manager python -I tools/oath.py delete github
    uv run --no-project --with yubikey-manager python -I tools/oath.py password set    # or: password clear

The key speaks the YubiKey OATH protocol, but ykman and Yubico Authenticator
refuse it (they only accept Yubico USB IDs), so this drives yubikit directly.
Secrets are typed at a hidden prompt, never given on the command line (shell
history). An account added with --touch needs BOOT or the touch pad for every
code. If an OATH password is set, the codes are only given after it.
"""
import argparse
import getpass
import struct
import sys
import time

from smartcard.System import readers
from ykman.pcsc import ScardSmartCardConnection
from yubikit import oath as yoath
from yubikit.core import Tlv
from yubikit.core.smartcard import ApduError
from yubikit.oath import (HASH_ALGORITHM, OATH_TYPE, Credential, CredentialData, OathSession,
                          parse_b32_key)

UPDATE_AID = [0xF0] + list(b"espfido")      # only esp32s3-fido keys answer this


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
        _, sw1, sw2 = c.transmit([0x00, 0xA4, 0x04, 0x00, len(UPDATE_AID)] + UPDATE_AID)
        if (sw1, sw2) == (0x90, 0x00):
            found.append((r, c))
        else:
            c.disconnect()
    if not found:
        sys.exit("no esp32s3-fido key found")
    if len(found) > 1:
        sys.exit("several keys found, pick one with --reader: " + ", ".join(str(r) for r, _ in found))
    return ScardSmartCardConnection(found[0][1])


def label(cred):
    return f"{cred.issuer}:{cred.name}" if cred.issuer else cred.name


def open_session(a):
    s = OathSession(find_key(a.reader))
    if s.locked:
        pw = getpass.getpass("OATH password: ")
        try:
            s.validate(s.derive_key(pw))
        except ApduError:
            sys.exit("wrong OATH password")
    return s


def pick(s, query):
    creds = s.list_credentials()
    exact = [c for c in creds if label(c).lower() == query.lower()]
    hits = exact or [c for c in creds if query.lower() in label(c).lower()]
    if not hits:
        sys.exit(f"no account matches {query!r}")
    if len(hits) > 1:
        sys.exit(f"{query!r} matches several accounts: " + ", ".join(label(c) for c in hits))
    return hits[0]


def put(s, d, touch):
    """OathSession.put_credential, but with the touch property as a real TLV.

    yubikit sends the YKOATH form `78 02` (no length byte); pico-fido parses
    every field as TLV and silently drops it, so the account would not ask
    for touch. `78 01 02` is what pico-fido understands.
    """
    secret = yoath._hmac_shorten_key(d.secret, d.hash_algorithm).ljust(yoath.HMAC_MINIMUM_KEY_SIZE, b"\0")
    data = Tlv(yoath.TAG_NAME, d.get_id()) + Tlv(
        yoath.TAG_KEY, struct.pack(">BB", d.oath_type | d.hash_algorithm, d.digits) + secret)
    if touch:
        data += Tlv(yoath.TAG_PROPERTY, bytes([yoath.PROP_REQUIRE_TOUCH]))
    if d.counter > 0:
        data += Tlv(yoath.TAG_IMF, struct.pack(">I", d.counter))
    s.protocol.send_apdu(0, yoath.INS_PUT, 0, 0, data)
    return Credential(s.device_id, d.get_id(), d.issuer, d.name, d.oath_type, d.period, touch)


def touch_note(cred):
    if cred.touch_required:
        print(f"{label(cred)}: press BOOT or touch the pad (LED blinks blue) ...", flush=True)


def calculate(s, cred):
    touch_note(cred)
    try:
        return s.calculate_code(cred)
    except ApduError as e:
        sys.exit(f"{label(cred)}: no code (SW {e.sw:04X}; not confirmed in time?)")


def show(cred, code):
    left = f"  ({code.valid_to - int(time.time())}s left)" if cred.oath_type == OATH_TYPE.TOTP else ""
    print(f"{label(cred):40} {code.value}{left}")


def do_list(s, a):
    creds = s.list_credentials()
    if not creds:
        print("no accounts")
    # LIST does not say which accounts need touch; CALCULATE ALL does (TOTP only)
    touch_ids = {c.id for c in s.calculate_all() if c.touch_required}
    for c in sorted(creds, key=label):
        kind = c.oath_type.name + (f"/{c.period}s" if c.oath_type == OATH_TYPE.TOTP else "")
        touch = ", touch" if c.id in touch_ids else ""
        print(f"{label(c):40} {kind}{touch}")


def do_code(s, a):
    if a.account:
        cred = pick(s, a.account)
        show(cred, calculate(s, cred))
        return
    codes = s.calculate_all()
    if not codes:
        print("no accounts")
    for cred in sorted(codes, key=label):
        code = codes[cred]
        if code is not None:
            show(cred, code)
        elif cred.oath_type == OATH_TYPE.HOTP:
            print(f"{label(cred):40} (HOTP: ask for it by name, each code moves the counter)")
        elif cred.touch_required:
            show(cred, calculate(s, cred))


def do_add(s, a):
    if a.name:
        secret = getpass.getpass("secret (Base32, as shown by the site): ")
        try:
            key = parse_b32_key(secret)
        except Exception:
            sys.exit("not a valid Base32 secret")
        data = CredentialData(name=a.name, issuer=a.issuer,
                              oath_type=OATH_TYPE.HOTP if a.hotp else OATH_TYPE.TOTP,
                              hash_algorithm=HASH_ALGORITHM[a.algorithm], secret=key,
                              digits=a.digits, period=a.period)
    else:
        uri = getpass.getpass("otpauth:// URI (from the QR code; input is hidden): ").strip()
        try:
            data = CredentialData.parse_uri(uri)
        except Exception as e:
            sys.exit(f"not a valid otpauth:// URI ({e})")
    lab = f"{data.issuer}:{data.name}" if data.issuer else data.name
    if any(label(c) == lab for c in s.list_credentials()) and not a.force:
        sys.exit(f"{lab!r} already exists (--force overwrites it)")
    try:
        cred = put(s, data, a.touch)
    except ApduError as e:
        sys.exit(f"the key refused the account (SW {e.sw:04X})")
    print(f"added {label(cred)} ({data.oath_type.name}, {data.digits} digits"
          + (", touch" if a.touch else "") + ")")
    if data.oath_type == OATH_TYPE.TOTP and not a.touch:
        show(cred, s.calculate_code(cred))


def do_rename(s, a):
    cred = pick(s, a.account)
    s.rename_credential(cred.id, a.name, a.issuer)
    print(f"renamed {label(cred)} -> {(a.issuer + ':') if a.issuer else ''}{a.name}")


def do_delete(s, a):
    cred = pick(s, a.account)
    if not a.yes and input(f"delete {label(cred)}? This cannot be undone [y/N] ").strip().lower() != "y":
        sys.exit("cancelled")
    s.delete_credential(cred.id)
    print(f"deleted {label(cred)}")


def do_password(s, a):
    if a.action == "clear":
        s.unset_key()
        print("OATH password removed")
        return
    pw = getpass.getpass("new OATH password: ")
    if not pw or pw != getpass.getpass("again: "):
        sys.exit("passwords empty or different")
    s.set_key(s.derive_key(pw))
    print("OATH password set (needed for codes and changes from now on)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reader", help="part of the smart card reader name, if several keys are plugged in")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the accounts")
    c = sub.add_parser("code", help="show codes (all TOTP, or one account)")
    c.add_argument("account", nargs="?", help="part of 'issuer:name'")
    ad = sub.add_parser("add", help="add an account (otpauth:// URI, or --name and a Base32 secret)")
    ad.add_argument("--name", help="account name; asks for the Base32 secret instead of a URI")
    ad.add_argument("--issuer")
    ad.add_argument("--hotp", action="store_true", help="counter based (default: TOTP)")
    ad.add_argument("--digits", type=int, choices=[6, 7, 8], default=6)
    ad.add_argument("--period", type=int, default=30)
    ad.add_argument("--algorithm", choices=["SHA1", "SHA256", "SHA512"], default="SHA1")
    ad.add_argument("--touch", action="store_true", help="require BOOT / touch for every code")
    ad.add_argument("--force", action="store_true", help="overwrite an account with the same name")
    rn = sub.add_parser("rename", help="rename an account")
    rn.add_argument("account")
    rn.add_argument("--name", required=True)
    rn.add_argument("--issuer")
    de = sub.add_parser("delete", help="delete an account")
    de.add_argument("account")
    de.add_argument("-y", "--yes", action="store_true")
    pw = sub.add_parser("password", help="set or clear the OATH password")
    pw.add_argument("action", choices=["set", "clear"])
    a = ap.parse_args()

    s = open_session(a)
    {"list": do_list, "code": do_code, "add": do_add, "rename": do_rename,
     "delete": do_delete, "password": do_password}[a.cmd](s, a)


if __name__ == "__main__":
    main()
