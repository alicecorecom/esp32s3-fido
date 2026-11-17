# Build the touch probe (same ESP-IDF setup as ..\..\idf.ps1).
#   .\probe.ps1 build
#   (flash: esptool write-flash --encrypt 0x20000 build\touchprobe.bin)
$ErrorActionPreference = 'Stop'
$IdfPath = 'D:\esp\v5.5.4\esp-idf'
$ToolsPath = 'D:\esp\.espressif'
$env:IDF_PATH = $IdfPath
$env:IDF_TOOLS_PATH = $ToolsPath
$py = Get-ChildItem "$ToolsPath\python_env\idf5.5_py*_env\Scripts\python.exe" | Select-Object -First 1
& $py.FullName "$IdfPath\tools\idf_tools.py" export --format key-value | ForEach-Object {
    $k, $v = $_ -split '=', 2
    if ($k -eq 'PATH') { $v = $v -replace '%PATH%', $env:PATH }
    Set-Item "env:$k" $v
}
$env:IDF_PATH = $env:IDF_PATH -replace '\\', '/'
$root = $PSScriptRoot
$build = Join-Path $root 'build'
$ErrorActionPreference = 'Continue'
& $py.FullName "$IdfPath\tools\idf.py" -C $root -B $build `
    -D "SDKCONFIG=$build\sdkconfig" -D "SDKCONFIG_DEFAULTS=$root\sdkconfig.probe" @args
exit $LASTEXITCODE
