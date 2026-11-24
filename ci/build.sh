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

idf.py -C "$proj" -B "$build" \
    -D "SDKCONFIG=$build/sdkconfig" -D "SDKCONFIG_DEFAULTS=$defaults" build
