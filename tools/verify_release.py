# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""Check a signed esp32s3-fido release zip against the attested unsigned build.

    uv run --no-project --with esptool python -I tools/verify_release.py \\
        esp32s3-fido-<ver>-devsb.zip esp32s3-fido-<ver>-devsb-unsigned.zip

The unsigned zip comes from GitHub Actions with an artifact attestation (it is
checked with `gh attestation verify` when the GitHub CLI is installed). The
signed zip is that build plus Secure Boot V2 signature sectors, added by the
author with tools/sign_release.py. This script checks that:

- every image in the signed zip is the attested one plus exactly one 4 KB
  signature sector, and every other file is identical;
- the signatures verify with every public key in keys/ (the keys the board
  burns into eFuse on its first devsb boot).

A standalone signed app (esp32s3-fido-<ver>-app-sb.bin / -app-rel.bin, for
tools/fwupdate.py) can be checked the same way: give it instead of the zip.
"""
import argparse
import contextlib
import glob
import io
import os
import shutil
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import espsecure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "alicecorecom/esp32s3-fido"
SIGNED_IMAGES = ("bootloader/bootloader.bin", "pico_fido.bin")


class Fail(Exception):
    pass


def zip_files(path):
    """{relative path inside the top folder: bytes}"""
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            rel = n.split("/", 1)[1] if "/" in n else n
            out[rel] = z.read(n)
    return out


def _verify_v2(datafile, keyfile):
    """espsecure.verify_signature_v2 across esptool versions: v5 takes keyword
    arguments, v4 (bundled with ESP-IDF 5.5) one argparse namespace."""
    try:
        return espsecure.verify_signature_v2(hsm=False, hsm_config=None, keyfile=keyfile, datafile=datafile)
    except TypeError:
        datafile.seek(0)
        keyfile.seek(0)
        return espsecure.verify_signature_v2(SimpleNamespace(datafile=datafile, keyfile=keyfile, hsm=False, hsm_config=None))


def verify_signatures(data, pubkeys, what):
    for k in pubkeys:
        f = io.BytesIO(open(k, "rb").read())
        f.name = k
        d = io.BytesIO(data)
        d.name = what
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                _verify_v2(d, f)
        except Exception as e:
            raise Fail(f"{what}: not signed by {os.path.basename(k)} ({e})")


def check_signed(signed, unsigned, pubkeys, what):
    if len(signed) != len(unsigned) + 0x1000 or signed[:-0x1000] != unsigned:
        raise Fail(f"{what}: is not the attested image plus one signature sector")
    if signed[-0x1000] != 0xE7:
        raise Fail(f"{what}: no Secure Boot V2 signature block")
    verify_signatures(signed, pubkeys, what)
    print(f"  ok  {what}: attested image + signatures by {len(pubkeys)} key(s)")


def attest(path):
    gh = shutil.which("gh")
    if not gh:
        print(f"  --  {os.path.basename(path)}: GitHub CLI not found, check it yourself:"
              f" gh attestation verify {path} --repo {REPO}")
        return
    r = subprocess.run([gh, "attestation", "verify", path, "--repo", REPO], capture_output=True, text=True)
    if r.returncode != 0:
        raise Fail(f"{os.path.basename(path)}: attestation check failed\n{r.stdout}{r.stderr}")
    print(f"  ok  {os.path.basename(path)}: built by {REPO} on GitHub Actions (attestation)")


def verify(signed_path, unsigned_zip, pubkeys, check_attestation=True):
    if check_attestation:
        attest(unsigned_zip)
    u = zip_files(unsigned_zip)
    if signed_path.endswith(".zip"):
        s = zip_files(signed_path)
        for name in SIGNED_IMAGES:
            if name not in s or name not in u:
                raise Fail(f"{name} missing")
            check_signed(s[name], u[name], pubkeys, name)
        for name, data in u.items():
            if name in SIGNED_IMAGES or name == "BUILDINFO.txt":
                continue
            if s.get(name) != data:
                raise Fail(f"{name}: differs from the attested build")
        print(f"  ok  other files identical: {', '.join(sorted(n for n in u if n not in SIGNED_IMAGES and n != 'BUILDINFO.txt'))}")
    else:
        check_signed(open(signed_path, "rb").read(), u["pico_fido.bin"], pubkeys, os.path.basename(signed_path))
    info = u.get("BUILDINFO.txt", b"").decode()
    for line in info.splitlines():
        if line.startswith(("app version", "app secure version", "app ELF SHA-256")):
            print(f"      {line}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("signed", help="signed zip, or a signed app .bin")
    ap.add_argument("unsigned", help="the matching *-unsigned.zip (attested)")
    ap.add_argument("--key", dest="keys", action="append", help="public key PEM, repeatable (default: keys/*.pub.pem)")
    ap.add_argument("--no-attestation", action="store_true", help="skip gh attestation verify")
    a = ap.parse_args()
    pubkeys = a.keys or sorted(glob.glob(os.path.join(ROOT, "keys", "*.pub.pem")))
    if not pubkeys:
        sys.exit("no public keys found in keys/")
    try:
        verify(a.signed, a.unsigned, pubkeys, not a.no_attestation)
    except Fail as e:
        sys.exit(f"FAILED: {e}")
    print("OK")


if __name__ == "__main__":
    main()
