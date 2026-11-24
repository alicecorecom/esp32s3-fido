# SPDX-License-Identifier: AGPL-3.0-only
# Run ESP-IDF's idf.py for this project without export.ps1.
# (export.ps1 calls `python` from PATH, which is the Microsoft Store stub on this PC.)
#
#   .\idf.ps1 dev build                 # unencrypted test build  -> build\dev
#   .\idf.ps1 release build             # flash-encrypted build   -> build\release
#   .\idf.ps1 dev -p COM9 flash monitor
#   .\idf.ps1 devsb -p COM9 encrypted-flash   # signs with 1Password keys, see below
#
# Extra arguments are passed to idf.py unchanged.
# No param() block on purpose: PowerShell would treat idf.py's "-p" as an
# abbreviation of a script parameter.
$ErrorActionPreference = 'Stop'
if ($args.Count -lt 1 -or $args[0] -notin @('dev', 'devenc', 'devsb', 'release')) {
    throw 'usage: .\idf.ps1 <dev|devenc|devsb|release> <idf.py arguments...>'
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

$idfPy = @("$IdfPath\tools\idf.py", '-C', $proj, '-B', $build,
    '-D', "SDKCONFIG=$build\sdkconfig", '-D', "SDKCONFIG_DEFAULTS=$defaults")

# Release writes are irreversible. Only `-p COMx encrypted-flash`, only onto a
# board that is in DEVELOPMENT flash encryption (SPI_BOOT_CRYPT_CNT = 0x1, i.e.
# it passed the devenc stage), and only with an explicit confirmation in the
# environment. ESP-IDF has no encrypted-flash target for a RELEASE-mode build,
# so the images are written with esptool's --encrypt (the chip encrypts them
# with its own key, as `encrypted-flash` does for devenc).
$flashActions = $IdfArgs | Where-Object { $_ -match 'flash$' }
if ($Profile -eq 'release' -and $flashActions) {
    if ($IdfArgs.Count -ne 3 -or $IdfArgs[0] -ne '-p' -or $IdfArgs[2] -ne 'encrypted-flash') {
        throw 'release: usage is .\idf.ps1 release -p COMx encrypted-flash'
    }
    if ($env:ESP32S3_FIDO_RELEASE_OK -ne 'yes') {
        throw 'release: irreversible. Set $env:ESP32S3_FIDO_RELEASE_OK = "yes" to confirm.'
    }
    $port = $IdfArgs[1]
    $ErrorActionPreference = 'Continue'
    & $py.FullName @idfPy build
    if ($LASTEXITCODE -ne 0) { throw 'release: build failed' }
    $info = & $py.FullName -m esptool --chip esp32s3 -p $port --after no_reset get_security_info 2>&1 | Out-String
    $ErrorActionPreference = 'Stop'
    if ($info -notmatch 'SPI_BOOT_CRYPT_CNT\)\s*:\s*0x1\b') {
        Write-Host $info
        throw 'release: board is not in DEVELOPMENT flash encryption (devenc). Refusing.'
    }
    Remove-Item Env:ESP32S3_FIDO_RELEASE_OK   # one confirmation per run
    Push-Location $build   # flash_args holds paths relative to the build directory
    try {
        $ErrorActionPreference = 'Continue'
        & $py.FullName -m esptool --chip esp32s3 -p $port -b 460800 --before default_reset --after no_reset `
            write_flash --encrypt '@flash_args'
        exit $LASTEXITCODE
    } finally { Pop-Location }
}

# devsb: Secure Boot V2. Only `-p COMx encrypted-flash`, only onto a board in
# DEVELOPMENT flash encryption. Builds, signs the bootloader and the app with
# every key in $env:ESP32S3_FIDO_SB_KEYS (1Password document names or IDs,
# ';'-separated, primary first) from vault $env:ESP32S3_FIDO_SB_VAULT, then
# writes them with --encrypt. If Secure Boot is not enabled on the board yet,
# its first boot burns the key digests (IRREVERSIBLE): that needs
# $env:ESP32S3_FIDO_SB_OK = "yes".
if ($Profile -eq 'devsb' -and $flashActions) {
    if ($IdfArgs.Count -ne 3 -or $IdfArgs[0] -ne '-p' -or $IdfArgs[2] -ne 'encrypted-flash') {
        throw 'devsb: usage is .\idf.ps1 devsb -p COMx encrypted-flash'
    }
    if (-not $env:ESP32S3_FIDO_SB_VAULT -or -not $env:ESP32S3_FIDO_SB_KEYS) {
        throw 'devsb: set $env:ESP32S3_FIDO_SB_VAULT and $env:ESP32S3_FIDO_SB_KEYS ("key1;key2")'
    }
    $port = $IdfArgs[1]
    $ErrorActionPreference = 'Continue'
    $info = & $py.FullName -m esptool --chip esp32s3 -p $port --after no_reset get_security_info 2>&1 | Out-String
    $ErrorActionPreference = 'Stop'
    if ($info -notmatch 'SPI_BOOT_CRYPT_CNT\)\s*:\s*0x1\b') {
        Write-Host $info
        throw 'devsb: board is not in DEVELOPMENT flash encryption (devenc). Refusing.'
    }
    $sbEnabled = $info -match 'Secure Boot:\s*Enabled'
    if (-not $sbEnabled -and $env:ESP32S3_FIDO_SB_OK -ne 'yes') {
        Write-Host $info
        throw 'devsb: Secure Boot is not enabled on this board; the first boot will burn eFuses. Set $env:ESP32S3_FIDO_SB_OK = "yes" to confirm.'
    }

    $ErrorActionPreference = 'Continue'
    & $py.FullName @idfPy build
    if ($LASTEXITCODE -ne 0) { throw 'devsb: build failed' }
    $signed = Join-Path $build 'signed'
    New-Item -ItemType Directory -Force $signed | Out-Null
    $keyArgs = @($env:ESP32S3_FIDO_SB_KEYS.Split(';') | Where-Object { $_ } | ForEach-Object { '--key', $_ })
    foreach ($img in 'bootloader\bootloader.bin', 'pico_fido.bin') {
        & $py.FullName -I (Join-Path $root 'tools\sbsign.py') --vault $env:ESP32S3_FIDO_SB_VAULT @keyArgs `
            (Join-Path $build $img) (Join-Path $signed (Split-Path $img -Leaf))
        if ($LASTEXITCODE -ne 0) { throw "devsb: signing $img failed" }
    }
    $ErrorActionPreference = 'Stop'
    # flash_args leaves the bootloader out under Secure Boot
    # (SECURE_BOOT_FLASH_BOOTLOADER_DEFAULT=n); add it from bootloader-flash_args
    # and point both images at the signed copies.
    $lines = @(Get-Content (Join-Path $build 'flash_args')) +
        @(Get-Content (Join-Path $build 'bootloader-flash_args') | Select-Object -Skip 1)
    $lines = $lines -replace ' bootloader/bootloader\.bin$', ' signed/bootloader.bin' `
        -replace ' pico_fido\.bin$', ' signed/pico_fido.bin'
    if (-not ($lines -match '^0x0 signed/bootloader\.bin$') -or -not ($lines -match ' signed/pico_fido\.bin$')) {
        throw "devsb: signed bootloader/app missing from the flash list:`n$($lines -join "`n")"
    }
    $lines | Set-Content -Encoding ascii (Join-Path $build 'signed_flash_args')

    if (-not $sbEnabled) { Remove-Item Env:ESP32S3_FIDO_SB_OK }   # one confirmation per run
    Push-Location $build
    try {
        $ErrorActionPreference = 'Continue'
        # Secure Boot builds select ESPTOOLPY_NO_STUB; do the same here.
        & $py.FullName -m esptool --chip esp32s3 -p $port -b 460800 --before default_reset --after no_reset --no-stub `
            write_flash --encrypt '@signed_flash_args'
        exit $LASTEXITCODE
    } finally { Pop-Location }
}

# idf.py/CMake print progress on stderr; do not treat that as a PowerShell error.
$ErrorActionPreference = 'Continue'
& $py.FullName @idfPy @IdfArgs
exit $LASTEXITCODE
