#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Linux build used by GitHub Actions (inside the espressif/idf image, after
# export.sh). Same sdkconfig layers as idf.ps1.
#   ci/build.sh <dev|devenc|release>   -> build/<profile>
set -eu
profile=${1:-}
case $profile in
    dev | devenc | release) ;;
    *) echo "usage: $0 <dev|devenc|release>" >&2; exit 2 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
proj=$root/pico-fido
build=$root/build/$profile
defaults="$proj/pico-keys-sdk/config/esp32/sdkconfig.defaults;$root/config/sdkconfig.common;$root/config/sdkconfig.$profile"

# App version: this repository's describe, as in idf.ps1 ("-dirty" ignores
# the submodule, which carries the applied patches).
ver=$(git -C "$root" describe --tags --always 2>/dev/null || echo unknown)
if [ -n "$(git -C "$root" status --porcelain --ignore-submodules=all --untracked-files=no 2>/dev/null)" ]; then
    ver="$ver-dirty"
fi
# Profile tag, as in idf.ps1 (fwupdate.py matches it against the key's state).
case $profile in
    dev) ver="$ver+dev" ;;
    devenc) ver="$ver+enc" ;;
    devsb) ver="$ver+sb" ;;
    release) ver="$ver+rel" ;;
esac

idf.py -C "$proj" -B "$build" \
    -D "SDKCONFIG=$build/sdkconfig" -D "SDKCONFIG_DEFAULTS=$defaults" \
    -D "PROJECT_VER=$ver" build
