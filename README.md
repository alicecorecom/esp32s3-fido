# esp32s3-fido

ESP32-S3 SuperMini を FIDO2 セキュリティキーにするファームウェア。
[pico-fido](https://github.com/polhenarejos/pico-fido) v8.2 を submodule で取り込み、`patches/` の2つのパッチで鍵の保護と使い勝手を改造している。

> [!WARNING]
> **サブの鍵・学習用です。** ESP32-S3 には専用のセキュリティチップが無く、グリッチ攻撃などへの耐性は市販のセキュリティキーに及びません。
> メインの鍵には市販品を使い、このキーは必ず他の手段（市販キーやリカバリーコード）と併用してください。

> [!IMPORTANT]
> **無線は使いません。** SuperMini は技適マークの無い基板のため、Wi-Fi / Bluetooth のコードをファームに含めていません。
> ビルド後に `.\check_no_radio.ps1` で確認できます。

## 目次

- [特長](#特長)
- [必要なもの](#必要なもの)
- [準備](#準備)
- [ビルド](#ビルド)
- [書き込み](#書き込み)
- [使い方](#使い方)
- [改造の詳細](#改造の詳細)
- [タッチの測定ツール](#タッチの測定ツール)
- [ライセンス](#ライセンス)

## 特長

| | pico-fido（本家） | esp32s3-fido |
|---|---|---|
| eFuse の鍵 | ソフトから読める | 読めない（HMAC 専用） |
| フラッシュと eFuse を吸い出されたら | 親鍵を復元される | 復元できない（release 時） |
| フラッシュ暗号化 | 有効にするとデータが読めなくなる | 使える |
| 本人確認 | 既定で無効 | BOOT ボタンかタッチパッドを待つ |
| 挿したときの Chrome の通知 | 「Pico Key detected」が毎回出る | 出ない |
| LED | 常に点滅 | 待機中は消灯、必要なときだけ光る |
| 乱数 | SAR ADC エントロピーを常時有効（タッチが使えない） | 起動時に CTR-DRBG を初期化 |
| USB の VID/PID・名前 | Raspberry Pi の番号（2E8A:10FE）、「Pol Henarejos / Pico Key」 | Espressif の VID（303A）、「Alice Core / ESP32-S3 FIDO2 Key」 |
| AAGUID（機種 ID） | pico-fido 共通（89fb94b7-…） | 独自（fcd33db5-11c4-4f13-9526-9fc4c1447732） |
| 作者のセキュアブート | 有効化すると作者署名のファームしか起動しない | 使わない |

## 必要なもの

- **ESP32-S3 SuperMini**（ESP32-S3FH4R2：フラッシュ 4MB、PSRAM 2MB、GPIO48 に WS2812 LED）
  - PSRAM は必須（データ領域 1MB をコピーして読むため）
- **タッチ電極**（任意）：GPIO1 に線をつなぎ、1〜2cm 角の銅テープなどを付けて薄い絶縁で覆う
  - 端子だけでは面積が足りず、テープ1枚越しでは反応しない
  - 使わない場合も BOOT ボタンで本人確認できる
- **ESP-IDF v5.5.4**（pico-fido 公式ビルドと同じ版）
- Windows + PowerShell（`idf.ps1` は PowerShell 用。Git Bash などの MSys 環境では ESP-IDF のツールが動かない）

## 準備

ESP-IDF を取得し、ツールと Python 環境を入れる。

```powershell
git clone -b v5.5.4 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git D:\esp\v5.5.4\esp-idf
$env:IDF_TOOLS_PATH = 'D:\esp\.espressif'
$py = uv python find 3.12
& $py D:\esp\v5.5.4\esp-idf\tools\idf_tools.py install --targets esp32s3
& $py D:\esp\v5.5.4\esp-idf\tools\idf_tools.py install-python-env
```

既定の場所は `D:\esp\v5.5.4\esp-idf` と `D:\esp\.espressif`。
ほかの場所に置いた場合は、環境変数 `IDF_PATH` と `IDF_TOOLS_PATH` で指定する。

## ビルド

```powershell
git submodule update --init --recursive
git -C pico-fido apply ../patches/pico-fido-esp32s3.patch
git -C pico-fido/pico-keys-sdk apply ../../patches/pico-keys-sdk-esp32s3.patch

.\idf.ps1 dev build          # 暗号化なし            -> build\dev
.\idf.ps1 devenc build       # 開発モードで暗号化    -> build\devenc
.\idf.ps1 release build      # release（本番）       -> build\release
.\check_no_radio.ps1         # 無線のコードが無いことを確認
```

- `idf.ps1` は、`export.ps1` を使わずに環境変数を設定して `idf.py` を呼ぶラッパー。2番目以降の引数は `idf.py` にそのまま渡す
- sdkconfig は、pico-keys-sdk の defaults → `config/sdkconfig.common` → `config/sdkconfig.<profile>` の順に重ねる
- パーティションテーブルは全プロファイル共通で 0x10000 に置く（暗号化入りのブートローダは 0x80C0 バイトあり、標準の 0x8000 では収まらない）

## 書き込み

> [!CAUTION]
> eFuse の書き込みとフラッシュ暗号化は **元に戻せません。** 必ず A → B → C の順に進め、
> 各段階で「PIN 設定 → 登録 → **抜き差し** → ログイン」まで確認してから次へ進んでください。

| 段階 | コマンド | 何が起きるか | 戻せるか |
|---|---|---|---|
| A. dev | `.\idf.ps1 dev -p COMx flash` | 初回起動で eFuse KEY3 を焼く | ファームは書き直せる |
| B. devenc | 初回：`.\idf.ps1 devenc -p COMx flash`<br>以降：`.\idf.ps1 devenc -p COMx encrypted-flash` | 初回起動でブートローダがフラッシュを暗号化する（開発モード） | 暗号化は解除できないが、`encrypted-flash` で書き直せる |
| C. release | `.\idf.ps1 release -p COMx encrypted-flash` | 起動時にアプリが release モードへ切り替え、secure download mode を有効にする | **戻せない。ファームも更新できなくなる** |

- 書き込むと USB が FIDO2 デバイスに切り替わり、COM ポートは消える。書き直すときは **BOOT を押しながら RST** を押してダウンロードモードに入れる
- 書き込んだあとは **基板の RST だけを押して** 起動する。USB 経由のリセットでは、手で入れたダウンロードモードから抜けられない
- B の間は盗難対策にならない（他人が自分のファームを書き込み、HMAC 回路を使える）。大事なアカウントは C の後に登録する
- C の後は、試験中の登録を消すため Windows の「セキュリティ キーのリセット」をする（親鍵も作り直される）

動作確認：
- PIN の設定・変更・リセット：Windows の「設定 → アカウント → サインイン オプション → セキュリティ キー」
- 登録・ログイン：https://webauthn.io（Edge / Chrome）

## 使い方

本人確認を求められたら、**タッチパッドに触れて離す** か **BOOT を押して離す**。15秒で時間切れになる。

| LED | 意味 |
|---|---|
| 青で0.5秒光って消える | 挿して USB が使えるようになった |
| 消灯 | 待機中・処理中 |
| 青で速く点滅 | タッチ / BOOT 待ち |
| 緑で0.5秒点灯 | 本人確認に成功 |
| 赤で0.5秒点灯 | 時間切れ・キャンセル |
| 赤でゆっくり点滅 | 挿して3秒経っても USB が使えない（充電専用ケーブルなど） |
| 赤で速く点滅 | 起動時の致命的エラー（eFuse の鍵・データ領域）。起動を止めている |

## 改造の詳細

改造した箇所には、ソースに `esp32s3-fido:` のコメントを入れてある。

<details>
<summary><b>1. eFuse の鍵を HMAC 専用にする</b>（<code>src/otp/otp_esp32.c</code>）</summary>

本家は eFuse KEY3/KEY4 に乱数鍵を **読み出し可能な USER ブロック** として焼き、ソフトで読んで親鍵（デバイス鍵）の暗号化に使う。
これだと、フラッシュと eFuse を吸い出されると親鍵を復元できる。

- eFuse **KEY3 を HMAC_UP 用** として1回だけ焼く。ハードが読み出し禁止にする（ソフトからも espefuse からも読めない）
- `otp_key_1` / `otp_key_2` は、毎回 `HMAC(KEY3, ラベル)` を HMAC 回路で計算する。KEY4 は使わない
- KEY3 が想定外の状態（USER 用のまま、読み出し可能など）なら **起動を止める**（弱い鍵では動かない）
- release ビルドは、開発モードで暗号化済みの基板を、起動時に release モードへ切り替える（`esp_flash_encryption_set_release_mode()`）。ブートローダは暗号化済みの基板を自動では切り替えないため

</details>

<details>
<summary><b>2. データ領域を mmap で読まない</b>（<code>src/fs/low_flash.c</code>）</summary>

本家は `part0`（鍵・PIN・登録などのデータ）を `esp_partition_mmap()` で読む。
フラッシュ暗号化が有効だと、キャッシュ経由の読み出しは **暗号化されていない領域も無条件に「復号」される**
（ESP-IDF `docs/en/security/flash-encryption.rst`）。このため本家のままでは、暗号化した瞬間にデータが読めなくなる。

- 起動時に `part0`（1MB）を **PSRAM に丸ごとコピー** し（`esp_partition_read_raw()`、復号しない）、以後はそこを読む
- 消去・書き込みのたびに、その範囲をフラッシュから読み直してコピーを更新する
- `part0` 自体は暗号化しない（pico-keys のジャーナルが、消去なしの上書きと 0xFF 判定を前提にしているため）
  - 中の親鍵は HMAC 由来の鍵で暗号化されているので、平文で置いても問題ない
  - **弱点**：盗んだ人が `part0` を古い状態に書き戻すと、PIN の残り回数を戻して総当たりを試せる（親鍵は取られない）

</details>

<details>
<summary><b>3. 本人確認を既定で有効にする</b>（<code>src/button.c</code>）</summary>

本家は、ESP32 では本人確認ボタンが **既定で無効**（待ち時間 0 = 押したことにする）。PicoKey App で設定する前提になっている。
これだと PC 上のソフトがキーを黙って使える。改造版では、未設定なら **BOOT（またはタッチパッド）を15秒待つ**。

</details>

<details>
<summary><b>4. タッチパッドでも本人確認できる</b>（<code>src/touch_button.c</code>、<code>src/button.c</code>）</summary>

GPIO1（TOUCH1）につないだ電極に触れても、ボタンを押した扱いにする（BOOT も引き続き使える）。

- 判定は「基準値 +8% を超えたら触った」。チャタリング防止に、20ms × 3回連続で確定する
- 基準値は自前で追従する（ESP-IDF のベンチマーク値は、ゆっくり触ると追いついてしまうため使わない）
  - 下がる方向はすぐ追従する（挿すときに触っていても、離せば戻る）
  - 上がる方向は、+4% 未満なら約10秒、+4〜8% なら約40秒かけて追従する（温度変化には追従し、触っている間は追従しない）
  - +8% を超えたまま30秒続いたら、その値を新しい基準にする（ケースや別の PC で待機時の値がずれても、押しっぱなしにならない）
- 本人確認の待ちが始まった時点で触れていたタッチは、一度離れるまで数えない（張り付いたパッドが勝手に承認したり、BOOT を妨げたりしない）
- チャンネルは `ESP32S3_FIDO_TOUCH_CHAN`（既定 1、-1 で無効）
- pico-fido の OTP 機能（ボタンを押した回数で文字を打つ）は、スロット未設定なら何もしない。スロットを設定する場合は誤タッチに注意

</details>

<details>
<summary><b>5. 乱数を CTR-DRBG にする</b>（<code>src/rng/hwrng.c</code> ほか）</summary>

本家は SAR ADC のエントロピー源（`bootloader_random_enable()`）を **ずっと有効のまま** にしている。
これが有効な間は、**タッチセンサーの値が固まって測定できない。**

ESP-IDF の推奨（`docs/en/api-reference/system/random.rst`：常時有効にできないなら、ハードウェア乱数で DRBG を初期化して使う）に従う。

- 起動時だけエントロピー源を有効にし、ハードウェア乱数で **mbedTLS CTR-DRBG** を初期化してから止める
- 以後の乱数は DRBG から作り、毎回 `esp_fill_random()` の値も追加入力として混ぜる
- DRBG の初期化に失敗したら、エントロピー源を止めずに本家と同じ動作に戻る（タッチは効かない）
- このため `config/mbedtls_config.h` で `MBEDTLS_CTR_DRBG_C` を ESP でも有効にし、`ctr_drbg.c` をビルドに加えた

</details>

<details>
<summary><b>6. 挿すたびの通知を止める</b>（<code>src/usb/usb_descriptors.c</code>）</summary>

本家は WebUSB の BOS 記述子でランディングページ（`https://www.picokeys.com`）を告知している。
Chrome はこれを見て、挿すたびに「Pico Key detected」の通知を出す。改造版では `iLandingPage` を 0 にした（WebUSB のインターフェース自体は残る）。

</details>

<details>
<summary><b>7. LED の光り方</b>（<code>src/led/</code>、pico-fido の <code>src/fido/fido.c</code>）</summary>

| 状態 | 本家 | 改造版 |
|---|---|---|
| 挿して USB が使えるようになった | 赤点滅 → 緑点滅（ずっと） | 青で0.5秒光って消灯 |
| 待機中・PC がスリープ中 | 緑点滅 / 青点滅 | 消灯 |
| 処理中 | 緑で細かく点滅 | 消灯 |
| 本人確認なしの要求の後 | 緑で3回点滅 | 光らない（`fido_led_3_blinks()`） |
| タッチ / BOOT 待ち | 黄でほぼ点灯 | 青で速く点滅（0.15秒、明るさ `ESP32S3_FIDO_BUTTON_BTNESS` = 6/15） |
| 本人確認の結果 | — | 成功は緑、失敗は赤で0.5秒点灯 |
| USB が使えない | 赤点滅 | 赤点滅（起動後3秒間は消灯） |
| 起動時の致命的エラー | 消灯のまま止まる | 赤で速く点滅 |

- 緑は「本人確認に成功した」ときだけ光る
- **色の順番**：LED ドライバは WS2812 標準の G→R→B で送るが、SuperMini には R→G→B で受け取る LED が載っている個体がある。
  既定は `PHY_LED_ORDER_GRB`（R と G を入れ替えて送る）。標準の WS2812 なら `-DESP32S3_FIDO_LED_ORDER=PHY_LED_ORDER_RGB` を指定する

</details>

<details>
<summary><b>8. USB の VID/PID と名前</b>（pico-fido の <code>CMakeLists.txt</code>、<code>src/usb/usb_descriptors.c</code>、<code>idf.ps1</code>）</summary>

本家の既定は Raspberry Pi の VID（2E8A:10FE）で、メーカー名は作者名になっている。
改造版は、ESP チップ搭載機器に無償で PID を割り当てている [Espressif の VID 0x303A](https://github.com/espressif/usb-pids) を使う。

- VID/PID は `idf.ps1` の `$UsbVid` / `$UsbPid` で指定する（`-D USB_VID=… -D USB_PID=…` で CMake に渡す）
- PID 0x83F8 は Espressif から割り当てを受けたこのプロジェクト専用の番号（[espressif/usb-pids#473](https://github.com/espressif/usb-pids/issues/473)）
- メーカー名・製品名は `ESP32S3_FIDO_USB_MANUFACTURER` / `ESP32S3_FIDO_USB_PRODUCT` で変えられる
- 認証器としての動作は VID/PID に依存しない（OS は HID の FIDO 用途ページで見分ける）。変えても登録は消えない

</details>

<details>
<summary><b>9. 独自の AAGUID</b>（pico-fido の <code>src/fido/cbor.c</code>）</summary>

AAGUID は認証器の機種を表す ID。本家のままだと pico-fido と同じ値を名乗るため、乱数で作った UUIDv4
`fcd33db5-11c4-4f13-9526-9fc4c1447732` に変えた。

- AAGUID は登録時にだけ送られるので、変えても既存の登録はそのまま使える
- attestation を求めないサイトや、自己署名の attestation では、ブラウザ / OS が AAGUID をゼロに置き換えてサイトに渡すことがある
- キーが名乗っている値は `tools/ccid/getinfo.py` で確認できる（CCID 経由。管理者権限は要らない）

```powershell
uv run --no-project --with pyscard python -I tools\ccid\getinfo.py
```

</details>

## タッチの測定ツール

`tools/touchprobe` は、ファームと同じ `touch_button.c` を動かし、測定値と判定を USB シリアルに 0.1秒ごとに表示する小さなアプリ。
電極の作りを変えたときに、触ったときの変化量が +8% を十分に超えるかを確かめるのに使う。

開発モードで暗号化済みの基板では、**アプリ領域だけ** を差し替える（データ領域は触らないので、PIN と登録は残る）。

```powershell
cd tools\touchprobe
.\probe.ps1 build
# ダウンロードモード（BOOT + RST）に入れてから
esptool --chip esp32s3 --port COMx write-flash --encrypt 0x20000 build\touchprobe.bin
# 元に戻す
..\..\idf.ps1 devenc -p COMx encrypted-flash
```

## ライセンス

[GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0-only）。

- 元になった pico-fido / pico-keys-sdk は Copyright (c) Pol Henarejos、AGPL-3.0-only。`patches/` の改造はその派生物で、同じライセンスに従う
- このリポジトリで新しく書いたもの（`idf.ps1`、`check_no_radio.ps1`、`config/`、`tools/touchprobe/`、パッチで追加する `touch_button.c/.h`）は Copyright (c) 2026 Alice Core、AGPL-3.0-only
- ESP-IDF（Apache-2.0）、TinyUSB（MIT）、Mbed TLS（Apache-2.0）などは、それぞれのライセンスに従う

ファームを書き込んだキーを人に渡す場合は、対応するソース（このリポジトリと、ビルドに使ったコミット）を入手できるようにしてください。
