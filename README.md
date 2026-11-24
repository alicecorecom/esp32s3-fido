# esp32s3-fido

ESP32-S3 SuperMini を FIDO2 セキュリティキーにするファームウェア。
[pico-fido](https://github.com/polhenarejos/pico-fido) v8.2 を submodule で取り込み、`patches/` の2つのパッチで鍵の保護と使い勝手を改造している。

> [!WARNING]
> **サブの鍵・学習用です。** ESP32-S3 には専用のセキュリティチップが無く、グリッチ攻撃などへの耐性は市販のセキュリティキーに及びません。
> メインの鍵には市販品を使い、このキーは必ず他の手段（市販キーやリカバリーコード）と併用してください。

> [!IMPORTANT]
> **無線は使いません。** SuperMini は技適マークの無い基板のため、Wi-Fi / Bluetooth のコードをファームに含めていません。
> ビルド後に `.\check_no_radio.ps1` で確認できます。

## 特長

| | pico-fido（本家） | esp32s3-fido |
|---|---|---|
| eFuse の鍵 | ソフトから読める | 読めない（HMAC 専用） |
| フラッシュと eFuse を吸い出されたら | 親鍵を復元される | 復元できない（release 時） |
| フラッシュ暗号化 | 有効にするとデータが読めなくなる | 使える |
| 本人確認 | 既定で無効 | BOOT ボタンかタッチパッドを待つ |
| PIN の最短の長さ | 4文字（FIDO2 の既定） | 8文字 |
| rescue アプレット（PicoKey App の窓口） | あり（設定の書き換え、デバイス鍵での署名、作者鍵のセキュアブート） | 外した |
| ファームの更新 | PicoKey App / ダウンロードモード | USB（CCID）経由、本人確認＋署名の確認つき |
| 挿したときの Chrome の通知 | 「Pico Key detected」が毎回出る | 出ない |
| LED | 常に点滅 | 待機中は消灯、必要なときだけ光る |
| 乱数 | SAR ADC エントロピーを常時有効（タッチが使えない） | 起動時に CTR-DRBG を初期化 |
| USB の VID/PID・名前 | Raspberry Pi の番号（2E8A:10FE）、「Pol Henarejos / Pico Key」 | Espressif の VID（303A）、「Alice Core / ESP32-S3 FIDO2 Key」 |
| AAGUID（機種 ID） | pico-fido 共通（89fb94b7-…） | 独自（fcd33db5-11c4-4f13-9526-9fc4c1447732） |
| セキュアブート | 有効化すると pico-fido の作者の署名しか起動しない | 配布版は esp32s3-fido の鍵（[`keys/`](keys/)、2本）。自分でビルドすれば自分の鍵にできる |
| パーティション | アプリ領域は1面（factory） | 2面（ota_0 / ota_1）。データ領域 part0 の位置は同じ |

## ダウンロード

[Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) から：

- **`esp32s3-fido-manager-<版>.exe`**：Windows 用の管理ツール（GUI）。新品の基板への書き込み、パスキー・PIN、ワンタイムパスワード、ファームの更新まで、これ1つでできる。macOS / Linux では uv から起動する（[管理ツール](docs/gui.md)）
- **`esp32s3-fido-<版>-devsb.zip` / `-release.zip`**：書き込むファーム（作者の鍵で署名済み）
- **`esp32s3-fido-<版>-app-rel.bin`**：使っているキーの更新用

どれも GitHub Actions でビルドし、本物かどうかを確かめられる（[配布バイナリ](docs/releases.md)）。

## はじめかた

新品の SuperMini を、**2回の書き込み**で使えるようにする。1回目（B+）で動作を確かめてから、2回目で本番（C）にする。どちらも元に戻せない。

1. 管理ツールの「キーを作る」タブで、最新版をダウンロードして確かめる
2. 基板をダウンロードモード（BOOT を押したまま RST）で挿し、「状態を読む」→ 1回目を書き込む → RST
3. LED の色合わせ、PIN の設定、登録と抜き差し後のログインを確かめる
4. もう一度ダウンロードモードにして 2回目を書き込む → RST → リセットして PIN を設定し直す

コマンドで行う手順と詳しい説明は [docs/getting-started.md](docs/getting-started.md)。

## ドキュメント

| ページ | 内容 |
|---|---|
| [はじめかた](docs/getting-started.md) | 新品の基板に配布版を書き込んで使い始めるまで（コマンド版） |
| [使い方](docs/usage.md) | 本人確認、LED、PIN、ファームの更新、ワンタイムパスワード、困ったとき |
| [管理ツール（GUI）](docs/gui.md) | 各タブでできること、起動のしかた |
| [配布バイナリ](docs/releases.md) | ファイルの一覧、本物か確かめる、ほかの書き込み方、作者向けの手順 |
| [自分でビルドする](docs/building.md) | ESP-IDF でのビルド、書き込みの段階、自分の鍵でのセキュアブート |
| [改造の詳細](docs/internals.md) | pico-fido から変えた14点、検討した結果、タッチの測定ツール |
| [セキュリティ](SECURITY.md) | 脆弱性の報告先 |

## ライセンス

[GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0-only）。

- 元になった pico-fido / pico-keys-sdk は Copyright (c) Pol Henarejos、AGPL-3.0-only。`patches/` の改造はその派生物で、同じライセンスに従う
- このリポジトリで新しく書いたもの（`idf.ps1`、`check_no_radio.ps1`、`config/`、`ci/`、`.github/`、`keys/`、`tools/sbsign.py`、`tools/fwupdate.py`、`tools/oath.py`、`tools/gui/`、`tools/sign_release.py`、`tools/verify_release.py`、`tools/touchprobe/`、パッチで追加する `touch_button.c/.h`・`fw_update.c`）は Copyright (c) 2026 Alice Core、AGPL-3.0-only
- ESP-IDF（Apache-2.0）、TinyUSB（MIT）、Mbed TLS（Apache-2.0）などは、それぞれのライセンスに従う

ファームを書き込んだキーを人に渡す場合は、対応するソース（このリポジトリと、ビルドに使ったコミット）を入手できるようにしてください。
