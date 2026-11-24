#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Packs build/<profile> into dist/esp32s3-fido-<version>-<profile>[-unsigned].zip
# and writes dist/SHA256SUMS. devsb and release are Secure Boot builds: their
# zips are unsigned and only serve as the attested input of
# tools/sign_release.py, which adds the signed zips to the release.
# Each zip carries BUILDINFO.txt (app version, secure version, ELF SHA-256 as
# shown by `tools/fwupdate.py info`, SHA-256 of every image).
#   ci/package.sh <version>
set -eu
version=${1:?usage: $0 <version>}
root=$(cd "$(dirname "$0")/.." && pwd)
dist=$root/dist
rm -rf "$dist"
mkdir -p "$dist"

for profile in dev devenc devsb release; do
    b=$root/build/$profile
    case $profile in
        devsb | release) name=esp32s3-fido-$version-$profile-unsigned ;;
        *) name=esp32s3-fido-$version-$profile ;;
    esac
    d=$dist/$name
    mkdir -p "$d/bootloader" "$d/partition_table"
    cp "$b/bootloader/bootloader.bin" "$d/bootloader/"
    cp "$b/partition_table/partition-table.bin" "$d/partition_table/"
    cp "$b/pico_fido.bin" "$b/ota_data_initial.bin" "$d/"
    case $profile in
        dev | devenc) cp "$b/flash_args" "$d/" ;;
    esac
    if [ "$profile" = devenc ]; then
        cp "$b/encrypted_flash_args" "$d/"
    fi
    python3 - "$b" "$d" "$profile" <<'EOF'
import hashlib, os, struct, sys
b, d, profile = sys.argv[1:]
app = open(os.path.join(d, "pico_fido.bin"), "rb").read()
desc = app[0x20:0x20 + 256]
assert struct.unpack("<I", desc[:4])[0] == 0xABCD5432, "no esp_app_desc_t"
s = lambda o, n: desc[o:o + n].split(b"\0")[0].decode()
lines = [
    f"profile: {profile}",
    f"app version: {s(16, 32)}",
    f"app secure version: {struct.unpack('<I', desc[4:8])[0]}",
    f"app ELF SHA-256: {desc[144:176].hex()}",
    f"ESP-IDF: {s(112, 32)}",
]
for root, _, files in os.walk(d):
    for f in sorted(files):
        p = os.path.join(root, f)
        rel = os.path.relpath(p, d).replace(os.sep, "/")
        lines.append(f"sha256 {hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {rel}")
open(os.path.join(d, "BUILDINFO.txt"), "w", newline="\n").write("\n".join(lines) + "\n")
print("\n".join(lines[:4]))
EOF
    (cd "$dist" && cmake -E tar cf "$name.zip" --format=zip "$name")
    rm -rf "$d"
done

(cd "$dist" && sha256sum ./*.zip | sed 's| [ *]\./|  |' > SHA256SUMS)   # GNU: " ./", Git Bash: "*./"
cat "$dist/SHA256SUMS"
