[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# はじめかた

配布版のファームを、**新品の** SuperMini に書き込んで使い始めるまでの手順。ESP-IDF は要らない。
書き込みは2回だけで、1回目（試験用の段階）で動作を確かめてから、2回目で本番の段階にする。

> [!TIP]
> [管理ツール（GUI）](gui.md#管理ツールgui)の「キーを作る」タブでも同じことができる。ファームのダウンロードと確認、書き込む前の基板の状態の確認（新品か、B+ で作者の鍵が焼かれているか）を自動で行い、想定と違う基板には書かない。
> 書き込むアドレスはツールの中で固定していて、zip の中の `flash_args` は使わない（`verify_release.py` が確かめる範囲の外のため）。

> [!CAUTION]
> この手順は eFuse を焼き、**元に戻せません。** 書き込んだ基板は、作者の鍵（[`keys/`](../keys/)）で署名したファームしか起動しなくなります。
> 自分の鍵を使いたい場合は、この手順を使わずに[自分でビルド](building.md#自分でビルドする)してください。

## 用意するもの

- **ESP32-S3 SuperMini**（ESP32-S3FH4R2：フラッシュ 4MB、PSRAM 2MB、GPIO48 に WS2812 LED）。PSRAM の無い型は使えない
- データ通信のできる USB-C ケーブル（充電専用のものは不可）
- Windows の PC と [uv](https://docs.astral.sh/uv/)（`esptool` と付属のツールを動かすのに使う）
- このリポジトリ一式（`git clone`、または GitHub の「Code → Download ZIP」）。付属のツール（`tools\`）と公開鍵（`keys\`）を使う
- タッチ電極（任意）：GPIO1 に線をつなぎ、1〜2cm 角の銅テープなどを付けて薄い絶縁で覆う。無くても BOOT ボタンで本人確認できる

以下のコマンドは、`tools\` を使うものはリポジトリのフォルダで、`esptool` を使うものは zip を展開したフォルダで実行する。`COMx` は基板の COM ポート（デバイス マネージャーの「ポート」に出る「USB シリアル デバイス」）に読み替える。

## 1. ファームを取ってくる

[Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) から次の4つをダウンロードし、zip を展開する。

- `esp32s3-fido-<版>-devsb.zip`（1回目に書く）
- `esp32s3-fido-<版>-release.zip`（2回目に書く）
- `esp32s3-fido-<版>-devsb-unsigned.zip` / `-release-unsigned.zip`（本物か確かめるのに使う）

本物か確かめる（任意だが推奨）。最後に `OK` と出ればよい（詳しくは[本物か確かめる](releases.md#本物か確かめる)）。

```powershell
uv run --no-project --with esptool python -I tools\verify_release.py <保存先>\esp32s3-fido-<版>-devsb.zip <保存先>\esp32s3-fido-<版>-devsb-unsigned.zip
uv run --no-project --with esptool python -I tools\verify_release.py <保存先>\esp32s3-fido-<版>-release.zip <保存先>\esp32s3-fido-<版>-release-unsigned.zip
```

## 2. 1回目の書き込み（試験用の段階 B+）

1. 基板の **BOOT を押したまま RST を押して離し**、BOOT も離す（ダウンロードモード）。COM ポートが現れる
2. 新品であることを確かめる。`SPI_BOOT_CRYPT_CNT` が `0x0`、`Secure Boot: Disabled`、`Key Purposes` が全部 0 であること
   ```powershell
   uvx esptool --chip esp32s3 -p COMx --no-stub get-security-info
   ```
3. `devsb` の zip を展開したフォルダで書き込む
   ```powershell
   uvx esptool --chip esp32s3 -p COMx --no-stub write-flash "@flash_args"
   ```
4. **基板の RST を押す**（書き込みツールのリセットでは、ダウンロードモードから抜けないことがある）。最初の起動で、セキュアブートとフラッシュの暗号化を有効にし、鍵を eFuse に焼く（十数秒）。終わると LED が青く0.5秒光る

## 3. 動作を確かめる

1. **LED の色を合わせる**。基板によって LED の赤と緑が入れ替わっているため、最初に一度やっておく（[詳しく](usage.md#led-の赤と緑が逆のとき)）
   ```powershell
   uv run --no-project --with pyscard python -I tools\fwupdate.py led-check
   ```
   LED が赤・緑の順に光るので、何色に見えたかを答える。途中で LED が青く点滅したら BOOT を押すかタッチする
2. **試しに使ってみる**
   - PIN を設定する：Windows の「設定 → アカウント → サインイン オプション → セキュリティ キー」（PIN は[8文字以上](usage.md#pin-は8文字以上にする)）
   - https://webauthn.io （Edge / Chrome）で登録し、**キーを抜き差しして**からログインできることを確かめる

ここまでで問題があれば、次へ進まない（この段階なら、署名済みのファームで書き直せる）。

## 4. 2回目の書き込み（本番の段階 C）

1. もう一度ダウンロードモードに入れ（BOOT を押したまま RST）、状態を確かめる。`SPI_BOOT_CRYPT_CNT` が `0x1`、`Secure Boot: Enabled` であること
   ```powershell
   uvx esptool --chip esp32s3 -p COMx --no-stub get-security-info
   ```
2. `release` の zip を展開したフォルダで書き込む（`--force` は、セキュアブートの有効な基板にブートローダを書くために要る）
   ```powershell
   uvx esptool --chip esp32s3 -p COMx --no-stub write-flash --force "@encrypted_flash_args"
   ```
3. **基板の RST を押す**。最初の起動で、暗号化を本番のモードに切り替え、ダウンロードモードでフラッシュを読めないようにする
4. キーを抜き差しして、手順 3 で登録したものでログインできることを確かめる

## 5. 本番用にする

1. 試験で登録したものを消すため、Windows の「セキュリティ キー」の画面で **リセット** する（キーの中の鍵も作り直される）
2. PIN を設定し直し（8文字以上）、使うサービスに登録する

以後のファームの更新は、挿したまま USB で行う（[ファームの更新](usage.md#ファームの更新)）。
