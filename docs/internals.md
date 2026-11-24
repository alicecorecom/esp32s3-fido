[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# 改造の詳細

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
<summary><b>8. USB の VID/PID と名前</b>（pico-fido の <code>CMakeLists.txt</code>、<code>src/usb/usb_descriptors.c</code>）</summary>

本家の既定は Raspberry Pi の VID（2E8A:10FE）で、メーカー名は作者名になっている。
改造版は、ESP チップ搭載機器に無償で PID を割り当てている [Espressif の VID 0x303A](https://github.com/espressif/usb-pids) を使う。

- VID/PID の既定値はパッチで pico-fido の `CMakeLists.txt` に入れてある（303A:83F8）。変えるときは `idf.py` に `-D USB_VID=… -D USB_PID=…` を渡す
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
- キーが名乗っている値は `tools/ccid/getinfo.py` で確認できる（CCID 経由。Windows では FIDO の窓口を開くので管理者権限が要る）

```powershell
uv run --no-project --with pyscard python -I tools\ccid\getinfo.py
```

</details>

<details>
<summary><b>10. OTA のロールバックに対応する</b>（<code>src/main.c</code>、<code>config/mbedtls_config.h</code>、<code>picokeys_sdk_import.cmake</code>）</summary>

ブートローダのロールバック機能（`config/sdkconfig.common`）は、更新したアプリを「確認待ち」で起動し、アプリが自分を「正常」と記録しないまま次に再起動すると、前の面に戻す。

- USB が使えるようになった時点で、1回だけ `esp_ota_mark_app_valid_cancel_rollback()` を呼ぶ。巻き戻し防止の版番号も、ここで eFuse に焼かれる
- esptool で書いたアプリは「確認待ち」にならないので、呼んでも何も変わらない（エラーを1行ログに出すだけ）
- セキュアブートを有効にすると、ESP-IDF はアプリ側でも更新イメージの署名を確かめる。その処理が mbedTLS のエントロピー機能を使うため、本家では無効の `MBEDTLS_ENTROPY_C` を ESP でも有効にし、`entropy.c` / `entropy_poll.c` をビルドに加えた（乱数源はハードウェアだけ。`MBEDTLS_NO_PLATFORM_ENTROPY`）

</details>

<details>
<summary><b>11. USB 経由のファーム更新</b>（<code>src/fw_update.c</code>、<code>tools/fwupdate.py</code>）</summary>

APDU で更新イメージを受け取るアプレット（AID `F0 65 73 70 66 69 64 6F`、"espfido"）を足した。CCID と WCID（WinUSB）の両方から届く。

| INS | 命令 | 内容 |
|---|---|---|
| 01 | INFO | 起動中の面と状態、アプリと eFuse の巻き戻し防止の版番号、アプリの版・ビルド日時・ESP-IDF の版、ELF SHA-256、セキュアブートと暗号化の状態 |
| 10 | BEGIN | 全体の大きさを受け取る。**本人確認が必須**（本人確認の設定にかかわらず必ず待つ） |
| 11 | WRITE | 位置＋データ。先頭から順番に書く（位置が飛んだら中止） |
| 12 | END | `esp_ota_end()` でイメージを検証（セキュアブートなら署名も）し、次の起動先にする |
| 13 / 14 | ABORT / REBOOT | 中止 / 応答を返してから再起動 |
| 20 | LED ORDER | LED の色の順番（P1 = `PHY_LED_ORDER_*`、0xFF で既定）。**本人確認が必須**。PHY データのこの項目だけを書く（以前は rescue アプレットの役目） |
| 21 | LED TEST | P1 = 1 赤 / 2 緑 / 3 青 を、今の色の順番で3回点滅させる（`led-check` が使う）。LED だけなので本人確認は求めない |

- 書き込みは `esp_ota_begin(…, OTA_WITH_SEQUENTIAL_WRITES)` で、書くそばから消去する（1MB を一度に消すと命令が長く止まるため）
- 別のアプレットが選ばれたら、書きかけのイメージは捨てる
- 試験済み（1台目、devsb）：本番の鍵で署名したものは受け付けて ota_0 → ota_1 に切り替わる。登録していない鍵の署名は END で拒否。「正常」と記録しない版に更新して再起動すると、前の面に戻る

</details>

<details>
<summary><b>12. rescue アプレットを外す</b>（<code>src/rescue.c</code>）</summary>

rescue アプレットは本家の設定アプリ（PicoKey App）の窓口で、次のことができる。どれも本人確認は要るが、esp32s3-fido には要らない窓口なので、ESP では登録しない（選ぶと `6A82`）。

- 設定（PHY）の書き換え：VID/PID、LED、**本人確認の待ち時間**（0 にすると BOOT / タッチを待たずに通る）など
- デバイス鍵（eFuse の HMAC 鍵から作る secp256k1 鍵）で、渡された32バイトに署名する
- **作者の鍵でセキュアブートの eFuse を焼く**（以後、作者が署名したファームしか起動しない。元に戻せない）

設定はすべてファームの既定値に入れてあり、セキュアブートは自分の鍵で有効にする（devsb / release）ので、失うものは無い。
起動時に呼ばれるデバイス鍵の移行処理（`rescue_migrate_keydev()`）は残している。

</details>

<details>
<summary><b>13. PIN の最短の長さを8文字にする</b>（pico-fido の <code>src/fido/fido.h</code>、<code>cbor_client_pin.c</code>、<code>cbor_config.c</code>、<code>cbor_get_info.c</code>）</summary>

FIDO2 の既定は4文字で、本家は authenticatorConfig（setMinPINLength）で長くできるだけ。ESP では、設定が無いときの既定値（`DEFAULT_MIN_PIN_LENGTH`）を8にした。

- getInfo の minPINLength も8を返す。PIN の設定・変更で8文字未満は `CTAP2_ERR_PIN_POLICY_VIOLATION` で断る
- 理由は[PIN は8桁以上にする](usage.md#pin-は8文字以上にする)を参照（フラッシュの書き戻しで失敗回数が戻る攻撃）
- すでに設定してある短い PIN は使える（照合では長さを見ない）。セキュリティキーのリセット後も8文字
- authenticatorConfig で8より長くはできる（短くはできない）

</details>

<details>
<summary><b>14. WR_DIS_RD_DIS をアプリが焼く</b>（<code>src/otp/otp_esp32.c</code>、<code>config/sdkconfig.devsb</code> / <code>.release</code>）</summary>

ESP-IDF のブートローダは、セキュアブートを有効にした最初の起動の最後に `WR_DIS_RD_DIS`（以後 eFuse を読み取り禁止にできなくする）を焼く。
改造1の HMAC の鍵はアプリが最初の起動で読み取り禁止にして焼くので、新品の基板に devsb / release を直接書くと、アプリの番にはもう読み取り禁止にできず、止まってしまう（release なら二度と書き直せない）。

- devsb / release では `CONFIG_SECURE_BOOT_V2_ALLOW_EFUSE_RD_DIS=y` にして、ブートローダには焼かせない（起動ログに「Allowing read disabling of additional efuses - SECURITY COMPROMISED」と出るのはこのため）
- アプリは HMAC の鍵を焼いて読み取り禁止を確かめた直後に、セキュアブートが有効なら `WR_DIS_RD_DIS` を焼く。毎回の起動で確かめ、焼いてあれば何もしない
- 窓が開いているのは新品の最初の起動の間だけで、その間に動くのは署名済みのブートローダとアプリだけ
- 段階を踏んで B+ にした基板（B+ の時点で古いブートローダが焼いた）とも、最終的な eFuse の状態は同じ

</details>

<details>
<summary>ハードウェア AES はそのまま使う（検討した結果）</summary>

ESP32-S3 には、汎用の AES 回路の鍵を電圧グリッチで取り出せるという勧告がある（[AR2026-005](https://documentation.espressif.com/AR2026-005_Security_Advisory_Concerning_AES_Key_Recovery_Using_Voltage_Fault_Injection_on%20ESP32-S3_EN.html)。フラッシュ暗号化の XTS-AES とは別の回路）。pico-fido では、パスキー本体は ChaCha20-Poly1305（ソフトウェア）で暗号化し、PIN で守るデータやファイルの AES-GCM と OTP がハードウェア AES を使う。

- 攻撃には基板の改造と FPGA のグリッチ装置が要り、Espressif の評価は「影響は低い」
- ソフトウェアの AES に替えても、CPU へのグリッチや電力解析に同じように弱いので、対策にならない
- 鍵はキーごとに違う（eFuse の HMAC 鍵から導出）ので、勧告が推す「デバイスごとに一意の鍵」は満たしている

物理的に盗まれたキーを専門の装置で解析されることへの耐性は、市販のセキュリティキーに及ばない（[README の冒頭の注意](../README.md)を参照）。

</details>

# タッチの測定ツール

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
