# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Alice Core
"""Sign the Secure Boot builds of a release with the keys in 1Password.

    # a tagged release (draft made by GitHub Actions): sign, verify, upload
    python -I tools/sign_release.py --tag v0.1.0 --upload
    # a manual (workflow_dispatch) run: sign and verify into --out only
    python -I tools/sign_release.py --run 45350947003 --out dist-signed
    # testing with a local ci/package.sh output (no attestation)
    python -I tools/sign_release.py --dist dist --out dist-signed

Run with the ESP-IDF Python (espsecure, cryptography). Keys: --vault / --key,
or $env:ESP32S3_FIDO_SB_VAULT and $env:ESP32S3_FIDO_SB_KEYS ("key1;key2"), as
for idf.ps1 devsb. Private keys are only read into memory (tools/sbsign.py).

For each *-devsb-unsigned.zip / *-release-unsigned.zip it:
1. checks the GitHub artifact attestation of the unsigned zip,
2. signs the bootloader and the app with every key,
3. writes esp32s3-fido-<ver>-<profile>.zip (signed images, the same
   partition table and otadata, encrypted_flash_args, BUILDINFO.txt) and the
   standalone signed app esp32s3-fido-<ver>-app-<sb|rel>.bin (tools/fwupdate.py),
4. checks the result with tools/verify_release.py against keys/*.pub.pem,
5. adds the new files to SHA256SUMS (and uploads them with --upload).
"""
import argparse
import contextlib
import glob
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espsecure  # noqa: E402
import sbsign  # noqa: E402
import verify_release  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = verify_release.REPO
APP_TAG = {"devsb": "sb", "release": "rel"}
FLASH_ARGS = """--flash_mode dio --flash_freq 80m --flash_size keep --encrypt
0x0 bootloader/bootloader.bin
0x10000 partition_table/partition-table.bin
0x18000 ota_data_initial.bin
0x20000 pico_fido.bin
"""


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def sign_bytes(data, pems):
    with tempfile.TemporaryDirectory() as t:
        src, dst = os.path.join(t, "in.bin"), os.path.join(t, "out.bin")
        open(src, "wb").write(data)          # unsigned image: public anyway
        with open(src, "rb") as f, contextlib.redirect_stdout(io.StringIO()):
            espsecure.sign_secure_boot_v2(SimpleNamespace(
                datafile=f, output=dst, keyfile=[io.BytesIO(p) for p in pems],
                signature=None, pub_key=None, append_signatures=False, hsm=False, hsm_config=None))
        return open(dst, "rb").read()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tag", help="release tag (draft created by the workflow)")
    src.add_argument("--run", help="workflow run ID (artifact 'dist')")
    src.add_argument("--dist", help="local ci/package.sh output (testing only: no attestation check)")
    ap.add_argument("--out", help="output directory (default: a new temp directory)")
    ap.add_argument("--upload", action="store_true", help="upload to the --tag release")
    ap.add_argument("--vault", default=os.environ.get("ESP32S3_FIDO_SB_VAULT"))
    ap.add_argument("--key", action="append",
                    default=[k for k in os.environ.get("ESP32S3_FIDO_SB_KEYS", "").split(";") if k] or None)
    a = ap.parse_args()
    if not a.vault or not a.key:
        sys.exit("give --vault and --key (or $env:ESP32S3_FIDO_SB_VAULT / _SB_KEYS)")
    if a.upload and not a.tag:
        sys.exit("--upload needs --tag")
    pubkeys = sorted(glob.glob(os.path.join(ROOT, "keys", "*.pub.pem")))

    out = a.out or tempfile.mkdtemp(prefix="esp32s3-fido-sign-")
    os.makedirs(out, exist_ok=True)
    if a.dist:
        for f in glob.glob(os.path.join(a.dist, "*.zip")) + glob.glob(os.path.join(a.dist, "SHA256SUMS")):
            shutil.copy(f, out)
    elif a.tag:
        gh("release", "download", a.tag, "-R", REPO, "-p", "*.zip", "-p", "SHA256SUMS", "-D", out, "--clobber")
    else:
        gh("run", "download", a.run, "-R", REPO, "-n", "dist", "-D", out)
    unsigned = sorted(glob.glob(os.path.join(out, "*-unsigned.zip")))
    if not unsigned:
        sys.exit(f"no *-unsigned.zip in {out}")

    op = sbsign.find_op()
    keys = [sbsign.read_key(op, a.vault, k) for k in a.key]
    pems = [pem for pem, _ in keys]
    print(f"signing with {len(pems)} key(s) from 1Password vault {a.vault!r}")
    # the keys must be the published ones, or nobody can verify the result
    from cryptography.hazmat.primitives import serialization as ser
    published = {ser.load_pem_public_key(open(p, "rb").read()).public_numbers() for p in pubkeys}
    for name, (_, k) in zip(a.key, keys):
        if k.public_key().public_numbers() not in published:
            sys.exit(f"{name!r} is not one of the published keys in keys/")

    new_files = []
    for uz in unsigned:
        base = os.path.basename(uz)[:-len("-unsigned.zip")]       # esp32s3-fido-<ver>-<profile>
        profile = base.rsplit("-", 1)[1]
        print(f"\n{os.path.basename(uz)}")
        if a.dist:
            print("  --  local build: no attestation to check")
        else:
            verify_release.attest(uz)
        files = verify_release.zip_files(uz)
        signed = {n: sign_bytes(files[n], pems) for n in verify_release.SIGNED_IMAGES}
        content = dict(files)
        content.update(signed)
        content["encrypted_flash_args"] = FLASH_ARGS.encode()
        info = files.get("BUILDINFO.txt", b"").decode().rstrip("\n").split("\n")
        info += ["signed: Secure Boot V2, keys " + ", ".join(os.path.basename(p) for p in pubkeys)]
        info += [f"sha256 {hashlib.sha256(signed[n]).hexdigest()}  {n} (signed)" for n in verify_release.SIGNED_IMAGES]
        content["BUILDINFO.txt"] = ("\n".join(info) + "\n").encode()

        zpath = os.path.join(out, base + ".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for n in sorted(content):
                z.writestr(f"{base}/{n}", content[n])
        app = os.path.join(out, f"{base.rsplit('-', 1)[0]}-app-{APP_TAG[profile]}.bin")
        open(app, "wb").write(signed["pico_fido.bin"])

        verify_release.verify(zpath, uz, pubkeys, check_attestation=False)
        verify_release.verify(app, uz, pubkeys, check_attestation=False)
        new_files += [zpath, app]

    sums = os.path.join(out, "SHA256SUMS")
    lines = open(sums).read().splitlines() if os.path.exists(sums) else []
    names = {os.path.basename(f) for f in new_files}
    lines = [l for l in lines if l.split()[-1] not in names]
    lines += [f"{hashlib.sha256(open(f, 'rb').read()).hexdigest()}  {os.path.basename(f)}" for f in new_files]
    open(sums, "w", newline="\n").write("\n".join(lines) + "\n")
    print("\nSHA256SUMS:\n" + "\n".join(lines))

    if a.upload:
        gh("release", "upload", a.tag, "-R", REPO, "--clobber", *new_files, sums)
        print(f"\nuploaded to the {a.tag} release (still a draft until you publish it)")
    else:
        print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
