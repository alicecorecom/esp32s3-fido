# esp32s3-fido

ESP32-S3 SuperMini（ピンヘッダなしの予備基板）を FIDO2 セキュリティキーにする実験。
[pico-fido](https://github.com/polhenarejos/pico-fido) v8.2（AGPL-3.0）を submodule で取り込み、
鍵の保護だけ改造している。

> **サブの鍵・学習用。** ESP32-S3 には専用のセキュリティチップが無く、グリッチ攻撃などへの耐性は市販キーに及ばない。
> メインの鍵は市販品を使い、このキーは必ず他の手段（市販キーやリカバリーコード）と併用する。

> **技適なし基板なので無線は使わない。** `config/sdkconfig.common` で BT / Wi-Fi を無効化してあり、
> ビルド結果に無線のコードは含まれない（`esp_wifi_*` / `esp_bt_*` のシンボル無しを確認済み）。

## 何を改造したか

本家 pico-fido は eFuse の KEY3/KEY4 に乱数鍵を **読み出し可能な USER ブロック** として焼き、ソフトで読んで
親鍵（デバイス鍵）の暗号化に使う。これだとフラッシュと eFuse を吸い出されると親鍵を復元できる。

改造版（`patches/pico-keys-sdk-otp-hmac.patch`、`otp_esp32.c` の `otp_platform_init()` のみ）:

- eFuse **KEY3 を HMAC_UP 用** として1回だけ焼く。HMAC 用の鍵はハードが読み出し禁止にする（ソフトにも espefuse にも読めない）
- `otp_key_1` / `otp_key_2` は毎回 `HMAC(KEY3, ラベル)` を HMAC 回路で計算して作る
- KEY3 が想定外の状態（USER のまま、読み出し可能など）なら **起動を止める**（弱い鍵で動かない）
- KEY4 は使わない

これに **フラッシュ暗号化（release）** を組み合わせると、他人のファームを書き込んで HMAC 回路を使われることも防げる。

| | 本家 | 改造版 |
|---|---|---|
| eFuse の鍵 | ソフトから読める | 読めない（HMAC 専用） |
| フラッシュ + eFuse を吸い出されたら | 親鍵を復元される | 復元できない |
| 作者のセキュアブート | 有効化すると作者署名のファームしか起動しない | 使わない |

## 準備（このPCでは済み）

ESP-IDF v5.5.4（pico-fido 公式ビルドと同じ版）を `D:\esp\v5.5.4\esp-idf`、ツールを `D:\esp\.espressif` に置いている。

```powershell
git clone -b v5.5.4 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git D:\esp\v5.5.4\esp-idf
$env:IDF_TOOLS_PATH = 'D:\esp\.espressif'
$py = uv python find 3.12
& $py D:\esp\v5.5.4\esp-idf\tools\idf_tools.py install --targets esp32s3
& $py D:\esp\v5.5.4\esp-idf\tools\idf_tools.py install-python-env
```

Git Bash からは動かない（MSys 非対応）。PowerShell で実行する。

## ビルド

```powershell
git submodule update --init --recursive
git -C pico-fido/pico-keys-sdk apply ../../patches/pico-keys-sdk-otp-hmac.patch
.\idf.ps1 dev build          # 暗号化なし（試験用） -> build\dev
```

`idf.ps1` は `export.ps1` を使わずに環境変数を設定して `idf.py` を呼ぶラッパー
（このPCの PATH の `python` は Microsoft Store のスタブで、`export.ps1` が動かないため）。
sdkconfig は `pico-keys-sdk の defaults` → `config/sdkconfig.common` → `config/sdkconfig.<profile>` の順に重ねる。

## 書き込み

書き込むと USB が pico-fido（TinyUSB）に切り替わり、COM ポートは消える。
書き直すときは **BOOT を押しながら RST**（または BOOT を押しながら挿す）でダウンロードモードに入れる。

```powershell
.\idf.ps1 dev -p COM9 flash
```

**初回起動で eFuse KEY3 が焼かれる（元に戻せない）。** dev プロファイルなら基板自体は書き直せる。

## ⚠ 既知の問題：今の release プロファイルは動かない（使わないこと）

pico-keys-sdk は `part0`（鍵などのデータ）を `esp_partition_mmap()` で読んでいる。
フラッシュ暗号化が有効だと、キャッシュ経由の読み出しは**暗号化されていない領域も無条件に「復号」される**
（ESP-IDF `docs/en/security/flash-encryption.rst`:
"Data which is stored unencrypted in flash memory will also be "transparently decrypted" via the flash cache and will appear to software as random garbage."）。
そのため release 化すると、書いたデータを正しく読み戻せず、Windows では「このセキュリティキーは使用できません」になる。

2026-11-17、SuperMini 2台目（40:F8:54）をこれで失った（release なので書き直し不可、廃棄）。

直すには `part0` の読み出しを mmap から `esp_partition_read()` に変える改造が要る（未対応）。
**release に進む前に、同じ設定を development モードの暗号化（書き直し可能）で実機検証すること。**

## 本番化（フラッシュ暗号化 release）— 元に戻せない

`config/sdkconfig.release`:
- **フラッシュ暗号化 release モード**（XTS-AES-128）
  - 暗号鍵は初回起動時にブートローダがチップ上で作る。誰にも分からず、読み出し禁止
- アプリは、暗号化が有効でなければ `abort()` する（`CONFIG_SECURE_FLASH_CHECK_ENC_EN_IN_APP`）
- ROM のダウンロードモードは **secure download mode**
  - フラッシュ・RAM の読み出しはできない
  - `espefuse summary` も使えなくなる（`esptool get-security-info` は使える）
- **パーティションテーブルを 0x10000 に移動**
  - 暗号化入りのブートローダは 0x80C0 バイトあり、標準位置 0x8000 だとはみ出す
- `part0`（鍵などのデータ）は暗号化しない
  - pico-keys のジャーナルが、消去なしの上書きと 0xFF 判定を前提にしているため
  - 中の親鍵は HMAC 由来の鍵で暗号化されているので、平文のままで構わない
  - **ただし読み出しが mmap のままだと壊れる（上の「既知の問題」）**

手順（BOOT+RST でダウンロードモードにした状態から）:

```powershell
.\idf.ps1 release build
uv run esptool --chip esp32s3 --port COM7 --before no-reset --after no-reset erase-region 0x200000 0x100000   # 試験中のデータを消す
.\idf.ps1 release -p COM7 flash      # 書き込み後はリセットしない設定
```

その後、基板の **RST だけを押す**（BOOT は押さない）。
- USB 経由のリセット（RTS や esptool の hard-reset）では、手で BOOT+RST した時のストラップ状態が残る
- そのため、何度リセットしてもダウンロードモードに戻ってしまう
- RST を押すと、初回起動でブートローダが暗号化を済ませ、FIDO キーとして起動する

## 個体

| 基板 | 状態 |
|---|---|
| SuperMini 2台目（MAC 末尾 40:F8:54、LED RGB） | **廃棄**。dev 版では PIN 設定・webauthn.io の登録/ログインまで成功し、KEY3 = HMAC_UP（読み出し禁止）も espefuse で確認した。2026-11-17 に release 化したところ、上記の既知の問題で動かなくなった |

FIDO2 の動作確認:
- Windows の「設定 → アカウント → サインイン オプション → セキュリティ キー」で PIN を設定
- https://webauthn.io で登録・ログインを試す
- ユーザー確認のボタンは **BOOT**
