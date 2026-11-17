# SPDX-License-Identifier: AGPL-3.0-only
# Run ESP-IDF's idf.py for this project without export.ps1.
# (export.ps1 calls `python` from PATH, which is the Microsoft Store stub on this PC.)
#
#   .\idf.ps1 dev build                 # unencrypted test build  -> build\dev
#   .\idf.ps1 release build             # flash-encrypted build   -> build\release
#   .\idf.ps1 dev -p COM9 flash monitor
#
# Extra arguments are passed to idf.py unchanged.
# No param() block on purpose: PowerShell would treat idf.py's "-p" as an
# abbreviation of a script parameter.
$ErrorActionPreference = 'Stop'
if ($args.Count -lt 1 -or $args[0] -notin @('dev', 'devenc', 'release')) {
    throw 'usage: .\idf.ps1 <dev|devenc|release> <idf.py arguments...>'
}
$Profile = $args[0]
$IdfArgs = @($args | Select-Object -Skip 1)

$IdfPath = if ($env:IDF_PATH) { $env:IDF_PATH } else { 'D:\esp\v5.5.4\esp-idf' }
$ToolsPath = if ($env:IDF_TOOLS_PATH) { $env:IDF_TOOLS_PATH } else { 'D:\esp\.espressif' }
$env:IDF_PATH = $IdfPath -replace '/', '\'
$env:IDF_TOOLS_PATH = $ToolsPath

$py = Get-ChildItem "$ToolsPath\python_env\idf5.5_py*_env\Scripts\python.exe" | Select-Object -First 1
if (-not $py) { throw "ESP-IDF python env not found under $ToolsPath" }

# Apply the variables idf_tools.py would export (PATH etc.).
& $py.FullName "$IdfPath\tools\idf_tools.py" export --format key-value | ForEach-Object {
    $k, $v = $_ -split '=', 2
    if ($k -eq 'PATH') { $v = $v -replace '%PATH%', $env:PATH }
    Set-Item "env:$k" $v
}
# Forward slashes for the build itself: pico-keys-sdk's CMake pastes $ENV{IDF_PATH}
# into CMake strings, where "\e" etc. would be parsed as escapes.
$env:IDF_PATH = $env:IDF_PATH -replace '\\', '/'

# USB VID/PID. 0x303A = Espressif's VID, free PIDs for ESP chips via
# https://github.com/espressif/usb-pids. 0x8000 is Espressif's test PID:
# temporary until our own PID is allocated.
$UsbVid = '0x303A'
$UsbPid = '0x8000'

$root = $PSScriptRoot
$proj = Join-Path $root 'pico-fido'
$build = Join-Path $root "build\$Profile"
$defaults = @(
    (Join-Path $proj 'pico-keys-sdk\config\esp32\sdkconfig.defaults'),
    (Join-Path $root 'config\sdkconfig.common'),
    (Join-Path $root "config\sdkconfig.$Profile")
) -join ';'

# SDKCONFIG_DEFAULTS only fill options missing from an existing sdkconfig, so an
# edit to config\sdkconfig.* would be ignored silently. Regenerate when stale.
$sdkconfig = Join-Path $build 'sdkconfig'
if (Test-Path $sdkconfig) {
    $cfgTime = (Get-Item $sdkconfig).LastWriteTime
    if ($defaults.Split(';') | Where-Object { (Get-Item $_).LastWriteTime -gt $cfgTime }) {
        Write-Host "sdkconfig defaults changed: regenerating $sdkconfig"
        Remove-Item $sdkconfig
    }
}

# Release writes are irreversible. Only allow `encrypted-flash` onto a board that
# is in DEVELOPMENT flash encryption (SPI_BOOT_CRYPT_CNT = 0x1, i.e. it passed the
# devenc stage), and only with an explicit confirmation in the environment.
$flashActions = $IdfArgs | Where-Object { $_ -match 'flash$' }
if ($Profile -eq 'release' -and $flashActions) {
    if ($flashActions | Where-Object { $_ -ne 'encrypted-flash' }) {
        throw "release: only 'encrypted-flash' is allowed (got: $($flashActions -join ', '))"
    }
    if ($env:ESP32S3_FIDO_RELEASE_OK -ne 'yes') {
        throw 'release: irreversible. Set $env:ESP32S3_FIDO_RELEASE_OK = "yes" to confirm.'
    }
    $i = [array]::IndexOf($IdfArgs, '-p')
    if ($i -lt 0 -or $i + 1 -ge $IdfArgs.Count) { throw 'release: pass the port with -p COMx' }
    $port = $IdfArgs[$i + 1]
    $ErrorActionPreference = 'Continue'
    $info = & $py.FullName -m esptool --chip esp32s3 -p $port --after no_reset get_security_info 2>&1 | Out-String
    $ErrorActionPreference = 'Stop'
    if ($info -notmatch 'SPI_BOOT_CRYPT_CNT\)\s*:\s*0x1\b') {
        Write-Host $info
        throw 'release: board is not in DEVELOPMENT flash encryption (devenc). Refusing.'
    }
    Remove-Item Env:ESP32S3_FIDO_RELEASE_OK   # one confirmation per run
}

# idf.py/CMake print progress on stderr; do not treat that as a PowerShell error.
$ErrorActionPreference = 'Continue'
& $py.FullName "$IdfPath\tools\idf.py" -C $proj -B $build `
    -D "SDKCONFIG=$build\sdkconfig" -D "SDKCONFIG_DEFAULTS=$defaults" `
    -D "USB_VID=$UsbVid" -D "USB_PID=$UsbPid" @IdfArgs
exit $LASTEXITCODE
