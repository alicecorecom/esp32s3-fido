# SPDX-License-Identifier: AGPL-3.0-only
"""Sign ESP-IDF images for Secure Boot V2 with RSA-3072 keys kept in 1Password.

The PEM keys go from `op document get` straight into memory and are handed to
espsecure as in-memory files: no key is ever written to disk. After signing,
every signature block is verified against the matching public key.

Run with the ESP-IDF Python (it has espsecure and cryptography):

    python tools/sbsign.py --vault "esp32s3-fido SB test" --key <item> [--key <item>] IN.bin OUT.bin
    python tools/sbsign.py --vault ... --key <item> [--key <item>] --digests

<item> is a 1Password document ID or title. Give the keys in a fixed order
(primary first): the bootloader burns one eFuse key slot per signature block.
--digests prints each key's Secure Boot V2 public key digest (the value burned
into eFuse, hex bytes separated by spaces as espefuse prints them) and signs
nothing.
"""
import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import espsecure
from cryptography.hazmat.primitives import serialization


def find_op():
    op = shutil.which("op")
    if op:
        return op
    # winget installs op.exe without putting it on PATH for every shell
    base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    for d in os.listdir(base) if os.path.isdir(base) else []:
        if d.startswith("AgileBits.1Password.CLI"):
            cand = os.path.join(base, d, "op.exe")
            if os.path.isfile(cand):
                return cand
    sys.exit("1Password CLI (op) not found")


def read_key(op, vault, item):
    r = subprocess.run([op, "document", "get", item, "--vault", vault],
                       capture_output=True)
    if r.returncode != 0:
        sys.exit(f"op document get {item!r} failed: {r.stderr.decode(errors='replace').strip()}")
    key = serialization.load_pem_private_key(r.stdout, None)
    if key.key_size != 3072:
        sys.exit(f"{item!r}: expected an RSA-3072 key, got {key.key_size} bits")
    return r.stdout, key


def key_digest(key):
    """SHA-256 of the key part of a Secure Boot V2 RSA signature block."""
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo)
    f = io.BytesIO(pub)
    f.name = "pub.pem"
    # espsecure writes the digest to a file; it is public, so a temp file is fine
    fd, path = tempfile.mkstemp()
    os.close(fd)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            espsecure.digest_sbv2_public_key(SimpleNamespace(keyfile=f, output=path))
        with open(path, "rb") as d:
            return d.read()
    finally:
        os.remove(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", required=True)
    ap.add_argument("--key", action="append", required=True, help="1Password document (repeat, up to 3)")
    ap.add_argument("--digests", action="store_true", help="print the eFuse key digests and exit")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    a = ap.parse_args()
    if len(a.key) > 3:
        sys.exit("Secure Boot V2 takes at most 3 signature blocks")
    if not a.digests:
        if not a.input or not a.output:
            ap.error("input and output are required unless --digests")
        if os.path.abspath(a.input) == os.path.abspath(a.output):
            sys.exit("output must differ from input")

    op = find_op()
    keys = [read_key(op, a.vault, k) for k in a.key]

    if a.digests:
        for _, key in keys:
            print(" ".join(f"{b:02x}" for b in key_digest(key)))
        return

    with open(a.input, "rb") as datafile:
        espsecure.sign_secure_boot_v2(SimpleNamespace(
            datafile=datafile, output=a.output,
            keyfile=[io.BytesIO(pem) for pem, _ in keys],
            signature=None, pub_key=None, append_signatures=False,
            hsm=False, hsm_config=None))

    for item, (_, key) in zip(a.key, keys):
        pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
        with open(a.output, "rb") as datafile:
            espsecure.verify_signature_v2(SimpleNamespace(
                datafile=datafile, keyfile=io.BytesIO(pub), hsm=False, hsm_config=None))
        print(f"verified: {item}")


if __name__ == "__main__":
    main()
