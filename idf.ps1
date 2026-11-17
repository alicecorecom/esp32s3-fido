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
if ($args.Count -lt 1 -or $args[0] -notin @('dev', 'release')) {
    throw 'usage: .\idf.ps1 <dev|release> <idf.py arguments...>'
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

# idf.py/CMake print progress on stderr; do not treat that as a PowerShell error.
$ErrorActionPreference = 'Continue'
& $py.FullName "$IdfPath\tools\idf.py" -C $proj -B $build `
    -D "SDKCONFIG=$build\sdkconfig" -D "SDKCONFIG_DEFAULTS=$defaults" @IdfArgs
exit $LASTEXITCODE
