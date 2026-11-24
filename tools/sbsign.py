# SPDX-License-Identifier: AGPL-3.0-only
"""Sign ESP-IDF images for Secure Boot V2 with RSA-3072 keys kept in 1Password.

The PEM keys go from `op document get` straight into memory and are handed to
espsecure as in-memory files: no key is ever written to disk. After signing,
every signature block is verified against the matching public key.

Run with the ESP-IDF Python (it has espsecure and cryptography):

    python tools/sbsign.py --vault "esp32s3-fido SB test" --key <item> [--key <item>] IN.bin OUT.bin

<item> is a 1Password document ID or title. Give the keys in a fixed order
(primary first): the bootloader burns one eFuse key slot per signature block.
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", required=True)
    ap.add_argument("--key", action="append", required=True, help="1Password document (repeat, up to 3)")
    ap.add_argument("input")
    ap.add_argument("output")
    a = ap.parse_args()
    if len(a.key) > 3:
        sys.exit("Secure Boot V2 takes at most 3 signature blocks")
    if os.path.abspath(a.input) == os.path.abspath(a.output):
        sys.exit("output must differ from input")

    op = find_op()
    keys = [read_key(op, a.vault, k) for k in a.key]

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
