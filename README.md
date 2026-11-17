# esp32s3-fido

ESP32-S3 SuperMini（ピンヘッダなしの予備基板）を FIDO2 セキュリティキーにする実験。
[pico-fido](https://github.com/polhenarejos/pico-fido) v8.2（AGPL-3.0）を submodule で取り込み、
`patches/pico-keys-sdk-esp32s3.patch` で pico-keys-sdk を改造している。

> **サブの鍵・学習用。** ESP32-S3 には専用のセキュリティチップが無く、グリッチ攻撃などへの耐性は市販キーに及ばない。
> メインの鍵は市販品を使い、このキーは必ず他の手段（市販キーやリカバリーコード）と併用する。

> **技適なし基板なので無線は使わない。** pico-fido は bt / esp_wifi コンポーネントを取り込まない。
> ビルド後に `.\check_no_radio.ps1` で、ELF に `esp_wifi_*` / `esp_bt_*` などが無いことを確認する。

## 改造の内容（`patches/pico-keys-sdk-esp32s3.patch`）

### 1. eFuse の鍵を HMAC 専用にする（`src/otp/otp_esp32.c`）

本家は eFuse KEY3/KEY4 に乱数鍵を **読み出し可能な USER ブロック** として焼き、ソフトで読んで親鍵（デバイス鍵）の暗号化に使う。
これだと、フラッシュと eFuse を吸い出されると親鍵を復元できる。

- eFuse **KEY3 を HMAC_UP 用** として1回だけ焼く。ハードが読み出し禁止にする（ソフトにも espefuse にも読めない）
- `otp_key_1` / `otp_key_2` は、毎回 `HMAC(KEY3, ラベル)` を HMAC 回路で計算する。KEY4 は使わない
- KEY3 が想定外の状態（USER のまま、読み出し可能など）なら **起動を止める**（弱い鍵では動かない）
- release ビルドは、開発モードで暗号化済みの基板を起動時に release へ切り替える（`esp_flash_encryption_set_release_mode()`）
  - ブートローダは、暗号化済みの基板を自動では切り替えないため

### 2. データ領域を mmap で読まない（`src/fs/low_flash.c`）

本家は `part0`（鍵・PIN・登録などのデータ）を `esp_partition_mmap()` で読む。
フラッシュ暗号化が有効だと、キャッシュ経由の読み出しは **暗号化されていない領域も無条件に「復号」される**
（ESP-IDF `docs/en/security/flash-encryption.rst`: "Data which is stored unencrypted in flash memory will also be
"transparently decrypted" via the flash cache and will appear to software as random garbage."）。
このため本家のままでは、暗号化した瞬間にデータが読めなくなる（2台目はこれで失った）。

- 起動時に `part0`（1MB）を **PSRAM に丸ごとコピー**し（`esp_partition_read_raw()`、復号しない）、以後はそこを読む
- 消去・書き込みのたびに、その範囲をフラッシュから読み直してコピーを更新する（アドレスは変わらない）
- `part0` 自体は暗号化しない（pico-keys のジャーナルが、消去なしの上書きと 0xFF 判定を前提にしているため）
  - 中の親鍵は HMAC 由来の鍵で暗号化されているので、平文で問題ない
  - **弱点**: 盗んだ人が `part0` を古い状態に書き戻すと、PIN の残り回数をリセットして総当たりを試せる（親鍵は取られない）

### 3. BOOT ボタンでの本人確認を既定で有効にする（`src/button.c`）

本家は、ESP32 では本人確認ボタンが **既定で無効**（待ち時間 0 = 押したことにする）。PicoKey App（有料）で設定する前提。
これだと PC 上のソフトがキーを黙って使える。改造版では、未設定なら **BOOT を15秒待つ**。

### 4. タッチパッドでも本人確認できる（`src/touch_button.c`、`src/button.c`）

GPIO1（TOUCH1）につないだ電極に触れても「ボタンを押した」扱いにする（BOOT も引き続き使える）。

- 実測（SuperMini 3台目、ビニール被覆の針金）:
  - 触っていない: 約 16,100（ばらつき ±10）
  - 手を近づけただけ: 最大 +2%
  - ビニール越しに触る: **+15%**
  - 金属をつまむ: +500% 以上
- 針金なし（基板の「1」の端子だけ、触っていない時 約 14,850）:
  - 端子にじかに触る: +9%〜+48%（触り方でばらつく。静電気がチップに直接入るので常用しない）
  - 端子にセロハンテープを1枚貼って上から押さえる: **+2.5%**（近づけただけと区別できない → 使えない）
  - → 電極は面積が要る。GPIO1 に線をはんだ付けし、1〜2cm 角の銅テープなどを付けて薄い絶縁で覆う
- 判定は「基準値 +8% を超えたら触った」。チャタリング防止に 20ms × 3回連続で確定
- 基準値は自前で追従する。ESP-IDF のベンチマーク値は、ゆっくり触ると追いついてしまうため使わない
  - 下がる方向はすぐ追従する（挿すときに触っていても、離せば戻る）
  - 上がる方向は、+4% 未満のときだけ約10秒かけて追従する（温度変化には追従し、触っている間は追従しない）
- チャンネルは `ESP32S3_FIDO_TOUCH_CHAN`（既定 1、-1 で無効）
- pico-fido の OTP 機能（ボタンを押した回数で文字を打つ）は、スロット未設定なら何もしない。スロットを設定する場合は誤タッチに注意

### 5. 乱数を DRBG にする（`src/rng/hwrng.c` ほか）

本家は SAR ADC のエントロピー源（`bootloader_random_enable()`）を **ずっと有効のまま** にしている。
これが有効な間は **タッチセンサーの値が固まって測定できない**（実測: 有効にした瞬間から値が一定のまま変化しなくなる）。

ESP-IDF の推奨（`docs/en/api-reference/system/random.rst`: 常時有効にできないなら、ハードウェア乱数で
DRBG を初期化して使う）に従う:
- 起動時だけエントロピー源を有効にし、ハードウェア乱数で **mbedTLS CTR-DRBG** を初期化してから止める
- 以後の乱数は DRBG から作り、毎回 `esp_fill_random()` の値も追加入力として混ぜる（RC_FAST クロック由来の二次エントロピー）
- DRBG の初期化に失敗したら、エントロピー源を止めずに本家と同じ動作に戻る（タッチは効かない）
- このため `config/mbedtls_config.h` で `MBEDTLS_CTR_DRBG_C` を ESP でも有効にし、`ctr_drbg.c` をビルドに加えた

### 6. 挿すたびの通知を止める（`src/usb/usb_descriptors.c`）

本家は WebUSB の BOS 記述子でランディングページ（`https://www.picokeys.com`）を告知している。
Chrome はこれを見て、挿すたびに「Pico Key detected」の通知を出す。改造版では `iLandingPage` を 0 にした
（WebUSB のインターフェース自体は残る）。

### 7. LED の光り方（`src/led/`）

| 状態 | 本家 | 改造版 |
|---|---|---|
| 挿して USB が使えるようになった | 赤点滅 → 緑点滅（ずっと） | **青で0.5秒光って消灯** |
| 待機中・PC がスリープ中 | 緑点滅 / 青点滅 | 消灯 |
| 処理中 | 緑で細かく点滅 | 同じ |
| タッチ / BOOT 待ち | 黄でほぼ点灯 | **白で速く点滅**（0.15秒） |
| 挿して3秒経っても USB が使えない（充電専用ケーブルなど） | 赤点滅 | 赤点滅（0.5秒） |
| 起動時の致命的エラー（eFuse 鍵・データ領域） | 消灯のまま止まる | **赤で速く点滅**（0.15秒） |

- **色の順番**: LED ドライバは WS2812 標準の G→R→B で送るが、SuperMini 1〜3台目の LED は R から受け取る個体なので、
  そのままだと赤と緑が入れ替わる（本家のままだと、正常に接続していても「赤点滅」に見えていた）。
  既定を `PHY_LED_ORDER_GRB`（r と g を入れ替えて送る）にした。標準の WS2812 なら `-DESP32S3_FIDO_LED_ORDER=PHY_LED_ORDER_RGB`
- 起動後3秒間は、USB が上がっていなくても消灯にしている（挿すたびに赤が一瞬光らないように）

| | 本家 | 改造版 |
|---|---|---|
| eFuse の鍵 | ソフトから読める | 読めない（HMAC 専用） |
| フラッシュ + eFuse を吸い出されたら | 親鍵を復元される | 復元できない（release 時） |
| フラッシュ暗号化 | データが読めなくなる | 動く |
| 本人確認ボタン | 既定で無効 | BOOT かタッチパッドを待つ |
| 挿したときの Chrome の通知 | 「Pico Key detected（picokeys.com へ）」が毎回出る | 出ない |
| 乱数 | SAR ADC エントロピーを常時有効 | 起動時に CTR-DRBG を初期化してから止める |
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
git -C pico-fido/pico-keys-sdk apply ../../patches/pico-keys-sdk-esp32s3.patch
.\idf.ps1 dev build          # 暗号化なし          -> build\dev
.\idf.ps1 devenc build       # 開発モードで暗号化  -> build\devenc
.\idf.ps1 release build      # release（本番）     -> build\release
.\check_no_radio.ps1         # 無線のコードが無いことを確認
```

`idf.ps1` は、`export.ps1` を使わずに環境変数を設定して `idf.py` を呼ぶラッパー
（このPCの PATH の `python` は Microsoft Store のスタブで、`export.ps1` が動かないため）。
sdkconfig は `pico-keys-sdk の defaults` → `config/sdkconfig.common` → `config/sdkconfig.<profile>` の順に重ねる。
パーティション配置（テーブルは 0x10000）は全プロファイル共通。暗号化入りブートローダは 0x80C0 バイトあり、標準の 0x8000 だとはみ出すため。

## 書き込みの流れ（3段階）

書き込むと USB が pico-fido（TinyUSB）に切り替わり、COM ポートは消える。
書き直すときは **BOOT を押しながら RST** でダウンロードモードに入れる。
**ダウンロードモードから抜けるときは、基板の RST だけを押す。** USB 経由のリセット（RTS や esptool の hard-reset）では
手で BOOT+RST した時のストラップ状態が残り、何度リセットしてもダウンロードモードに戻る。

各段階で、PIN 設定 → webauthn.io で登録 → **抜き差し** → ログイン、まで確認してから次へ進む。

| 段階 | コマンド | 何が起きるか | 戻せるか |
|---|---|---|---|
| A. dev | `.\idf.ps1 dev -p COM8 flash` | 初回起動で eFuse KEY3 を焼く | 基板は書き直せる |
| B. devenc | 初回: `.\idf.ps1 devenc -p COM8 flash` → RST<br>以降: `.\idf.ps1 devenc -p COM8 encrypted-flash` → RST | 初回起動でブートローダがフラッシュを暗号化（開発モード） | 暗号化は解除できないが、`encrypted-flash` で書き直せる |
| C. release | `.\idf.ps1 release -p COM8 encrypted-flash` → RST | 起動時にアプリが release へ切り替え、secure download mode を有効化 | **戻せない。ファームも更新できなくなる** |

- B の間は盗難対策にならない（他人が自分のファームを書き込んで、HMAC 回路を使える）。大事なアカウントは C の後に登録する
- C の後は試験中の登録を消すため、Windows の「セキュリティ キーのリセット」をする（親鍵も作り直される。B で動作確認済み）

## タッチの測定ツール（`tools/touchprobe`）

ファームと同じ `touch_button.c` を動かし、値を USB シリアルに 0.1 秒ごとに表示する小さなアプリ。
開発モードで暗号化済みの基板では、**アプリ領域だけ** を差し替える（データ領域は触らないので PIN・登録は残る）。

```powershell
cd tools\touchprobe
.\probe.ps1 build
# BOOT+RST でダウンロードモードにしてから（測定ツールが動いている間は COM ポートがあるので不要）
uv run --project ..\..\..\esp32s3-supermini esptool --chip esp32s3 --port COM8 write-flash --encrypt 0x20000 build\touchprobe.bin
# 戻すとき: ..\..\idf.ps1 devenc -p COM8 encrypted-flash
```

## 個体

| 基板 | 状態 |
|---|---|
| SuperMini 2台目（40:F8:54） | **廃棄**。改造2が無い状態で release 化し、データが読めなくなった（2026-11-17） |
| SuperMini 3台目（40:F9:60、LED RGB） | **段階 B（開発モードで暗号化）で様子見中**（2026-11-18〜）。A・B とも、抜き差し後のログイン、リセット、BOOT 必須を確認済み。リセット直後に1回だけ BOOT が効かず、挿し直しで直った（再現せず）。GPIO1 にビニール被覆の針金をつけ、タッチでのログインを確認済み |

FIDO2 の動作確認:
- Windows の「設定 → アカウント → サインイン オプション → セキュリティ キー」で PIN の設定・変更・リセット
- https://webauthn.io で登録・ログイン（Edge / Chrome）
- 本人確認は **BOOT** か **GPIO1 のタッチパッド**（触って離す。15秒で時間切れ）
