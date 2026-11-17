# SPDX-License-Identifier: AGPL-3.0-only
# Fails if a built ELF contains Wi-Fi / Bluetooth code (this board has no 技適).
#   .\check_no_radio.ps1            # checks every build\<profile>\pico_fido.elf
$ErrorActionPreference = 'Stop'
$nm = Get-ChildItem 'D:\esp\.espressif\tools\xtensa-esp-elf\*\xtensa-esp-elf\bin\xtensa-esp32s3-elf-nm.exe' | Select-Object -First 1
$bad = 0
foreach ($elf in Get-ChildItem (Join-Path $PSScriptRoot 'build\*\pico_fido.elf')) {
    $hits = & $nm.FullName $elf.FullName | Select-String -Pattern ' [TtWw] (esp_wifi_\w+|esp_bt_\w+|esp_ble_\w+|esp_now_\w+|ieee80211_\w+)$'
    if ($hits) {
        "NG  $($elf.Directory.Name): $($hits.Count) radio symbols"; $hits | Select-Object -First 5 | ForEach-Object { "    $($_.Line)" }
        $bad++
    } else {
        "OK  $($elf.Directory.Name): no radio symbols"
    }
}
exit $bad
