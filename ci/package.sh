#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Packs build/<profile> into dist/esp32s3-fido-<version>-<profile>.zip and
# writes dist/SHA256SUMS.
#   ci/package.sh <version>
set -eu
version=${1:?usage: $0 <version>}
root=$(cd "$(dirname "$0")/.." && pwd)
dist=$root/dist
rm -rf "$dist"
mkdir -p "$dist"

for profile in dev devenc release; do
    b=$root/build/$profile
    name=esp32s3-fido-$version-$profile
    d=$dist/$name
    mkdir -p "$d/bootloader" "$d/partition_table"
    cp "$b/bootloader/bootloader.bin" "$d/bootloader/"
    cp "$b/partition_table/partition-table.bin" "$d/partition_table/"
    cp "$b/pico_fido.bin" "$b/flash_args" "$d/"
    if [ "$profile" != dev ]; then
        cp "$b/encrypted_flash_args" "$d/"
    fi
    (cd "$dist" && cmake -E tar cf "$name.zip" --format=zip "$name")
    rm -rf "$d"
done

(cd "$dist" && sha256sum ./*.zip | sed 's| \./| |' > SHA256SUMS)
cat "$dist/SHA256SUMS"
