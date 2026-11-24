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
- [はじめかた](#はじめかた) — 配布版を新品の基板に書き込んで使い始めるまで
- [使い方](#使い方) — 本人確認、LED、PIN、ファームの更新、ワンタイムパスワード、困ったとき
- [配布バイナリの詳細](#配布バイナリの詳細) — ファームの一覧と、本物かどうかの確かめ方、ほかの書き込み方
- [自分でビルドする](#自分でビルドする) — ESP-IDF でのビルドと、自分の鍵を使ったセキュアブート
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
| PIN の最短の長さ | 4文字（FIDO2 の既定） | 8文字 |
| rescue アプレット（PicoKey App の窓口） | あり（設定の書き換え、デバイス鍵での署名、作者鍵のセキュアブート） | 外した |
| ファームの更新 | PicoKey App / ダウンロードモード | USB（CCID）経由、本人確認＋署名の確認つき |
| 挿したときの Chrome の通知 | 「Pico Key detected」が毎回出る | 出ない |
| LED | 常に点滅 | 待機中は消灯、必要なときだけ光る |
| 乱数 | SAR ADC エントロピーを常時有効（タッチが使えない） | 起動時に CTR-DRBG を初期化 |
| USB の VID/PID・名前 | Raspberry Pi の番号（2E8A:10FE）、「Pol Henarejos / Pico Key」 | Espressif の VID（303A）、「Alice Core / ESP32-S3 FIDO2 Key」 |
| AAGUID（機種 ID） | pico-fido 共通（89fb94b7-…） | 独自（fcd33db5-11c4-4f13-9526-9fc4c1447732） |
| セキュアブート | 有効化すると作者署名のファームしか起動しない | 作者の鍵は使わない。自分の鍵で有効にする（devsb / release） |
| パーティション | アプリ領域は1面（factory） | 2面（ota_0 / ota_1）。データ領域 part0 の位置は同じ |

## はじめかた

配布版のファームを、**新品の** SuperMini に書き込んで使い始めるまでの手順。ESP-IDF は要らない。
書き込みは2回だけで、1回目（試験用の段階）で動作を確かめてから、2回目で本番の段階にする。

> [!CAUTION]
> この手順は eFuse を焼き、**元に戻せません。** 書き込んだ基板は、作者の鍵（[`keys/`](keys/)）で署名したファームしか起動しなくなります。
> 自分の鍵を使いたい場合は、この手順を使わずに[自分でビルド](#自分でビルドする)してください。

### 用意するもの

- **ESP32-S3 SuperMini**（ESP32-S3FH4R2：フラッシュ 4MB、PSRAM 2MB、GPIO48 に WS2812 LED）。PSRAM の無い型は使えない
- データ通信のできる USB-C ケーブル（充電専用のものは不可）
- Windows の PC と [uv](https://docs.astral.sh/uv/)（`esptool` と付属のツールを動かすのに使う）
- このリポジトリ一式（`git clone`、または GitHub の「Code → Download ZIP」）。付属のツール（`tools\`）と公開鍵（`keys\`）を使う
- タッチ電極（任意）：GPIO1 に線をつなぎ、1〜2cm 角の銅テープなどを付けて薄い絶縁で覆う。無くても BOOT ボタンで本人確認できる

以下のコマンドは、`tools\` を使うものはリポジトリのフォルダで、`esptool` を使うものは zip を展開したフォルダで実行する。`COMx` は基板の COM ポート（デバイス マネージャーの「ポート」に出る「USB シリアル デバイス」）に読み替える。

### 1. ファームを取ってくる

[Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) から次の4つをダウンロードし、zip を展開する。

- `esp32s3-fido-<版>-devsb.zip`（1回目に書く）
- `esp32s3-fido-<版>-release.zip`（2回目に書く）
- `esp32s3-fido-<版>-devsb-unsigned.zip` / `-release-unsigned.zip`（本物か確かめるのに使う）

本物か確かめる（任意だが推奨）。最後に `OK` と出ればよい（詳しくは[本物か確かめる](#本物か確かめる)）。

```powershell
uv run --no-project --with esptool python -I tools\verify_release.py <保存先>\esp32s3-fido-<版>-devsb.zip <保存先>\esp32s3-fido-<版>-devsb-unsigned.zip
uv run --no-project --with esptool python -I tools\verify_release.py <保存先>\esp32s3-fido-<版>-release.zip <保存先>\esp32s3-fido-<版>-release-unsigned.zip
```

### 2. 1回目の書き込み（試験用の段階 B+）

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

### 3. 動作を確かめる

1. **LED の色を合わせる**。基板によって LED の赤と緑が入れ替わっているため、最初に一度やっておく（[詳しく](#led-の赤と緑が逆のとき)）
   ```powershell
   uv run --no-project --with pyscard python -I tools\fwupdate.py led-check
   ```
   LED が赤・緑の順に光るので、何色に見えたかを答える。途中で LED が青く点滅したら BOOT を押すかタッチする
2. **試しに使ってみる**
   - PIN を設定する：Windows の「設定 → アカウント → サインイン オプション → セキュリティ キー」（PIN は[8文字以上](#pin-は8文字以上にする)）
   - https://webauthn.io（Edge / Chrome）で登録し、**キーを抜き差しして**からログインできることを確かめる

ここまでで問題があれば、次へ進まない（この段階なら、署名済みのファームで書き直せる）。

### 4. 2回目の書き込み（本番の段階 C）

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

### 5. 本番用にする

1. 試験で登録したものを消すため、Windows の「セキュリティ キー」の画面で **リセット** する（キーの中の鍵も作り直される）
2. PIN を設定し直し（8文字以上）、使うサービスに登録する

以後のファームの更新は、挿したまま USB で行う（[ファームの更新](#ファームの更新)）。

## 使い方

### 本人確認

ログインなどで本人確認を求められると、LED が青く速く点滅する。**タッチパッドに触れて離す** か **BOOT を押して離す**。15秒で時間切れになる。

| LED | 意味 |
|---|---|
| 青で0.5秒光って消える | 挿して USB が使えるようになった |
| 消灯 | 待機中・処理中 |
| 青で速く点滅 | タッチ / BOOT 待ち |
| 緑で0.5秒点灯 | 本人確認に成功 |
| 赤で0.5秒点灯 | 時間切れ・キャンセル |
| 赤でゆっくり点滅 | 挿して3秒経っても USB が使えない（充電専用ケーブルなど） |
| 赤で速く点滅 | 起動時の致命的エラー（eFuse の鍵・データ領域）。起動を止めている |
| 挿しても何も光らない | アプリが起動していない（[困ったとき](#困ったとき)） |

### PIN は8文字以上にする

PIN は **8文字以上**（英字や記号も混ぜられる。最大63バイト）にする。キーは間違いを8回で締め出すが、それだけに頼れないため。
ファームも8文字未満の PIN を断る（Windows では「もう少し複雑な PIN にしてください」と出る）。この制限の前に設定した短い PIN はそのまま使えるので、PIN の変更で8文字以上にしておく。

- フラッシュを丸ごと吸い出して後で書き戻すと、PIN の失敗回数も元に戻る（[Token2 の勧告](https://www.token2.com/img/T2-SA-RP2350-Dec2025.pdf)、pico-fido 共通）。これを繰り返せば PIN を総当たりできる
- 勧告の見積もりでは、総当たりにかかる時間は **4桁で約8時間、6桁で約34日、8桁で約10年**
- esp32s3-fido では、ダウンロードモードが開いている段階（dev / devenc / devsb）の間はこの吸い出しと書き戻しができる。本番の段階（release）ではダウンロードモードでフラッシュを読めず、フラッシュもチップに内蔵なので、かなり難しくなる
- PIN の保存方法の弱さ（吸い出したデータから PIN を割り出せた）は、pico-fido の commit 6c85421 で直っていて、v8.2 に入っている

### ファームの更新

挿したまま USB で更新できる（ダウンロードモードも管理者権限も要らない）。登録済みのパスキーと PIN はそのまま残る。

1. [Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) から、キーの段階に合ったアプリをダウンロードする。[はじめかた](#はじめかた)のとおりに書いたキーなら `esp32s3-fido-<版>-app-rel.bin`
2. 更新する
   ```powershell
   uv run --no-project --with pyscard python -I tools\fwupdate.py update <保存先>\esp32s3-fido-<版>-app-rel.bin
   ```
3. LED が青く点滅したら BOOT を押すかタッチする。30秒ほどで書き終わり、キーが再起動する
4. `info` で新しい版になったことを確かめる
   ```powershell
   uv run --no-project --with pyscard python -I tools\fwupdate.py info
   ```

| キーの段階（`info` の表示） | 送るファイル |
|---|---|
| `secure boot: on`、`flash encryption: release` | `app-rel.bin` |
| `secure boot: on`、`flash encryption: development` | `app-sb.bin` |
| `secure boot: off` | dev / devenc の zip の `pico_fido.bin` |

- 書き終わるとキー自身がイメージを検証する。セキュアブートの基板では **登録した鍵の署名と、巻き戻し防止の版番号も確かめ、合わなければ受け付けない**（ツール側の検査を飛ばしても同じ）
- 新しいファームは「確認待ち」で起動し、USB がつながると自分を「正常」と記録する。記録しないまま再起動すると、ブートローダが前の版に戻す
- `fwupdate.py` はキーの段階に合わないファイルを送らない（`+rel` のアプリは起動すると基板を本番の段階に切り替えるので、devsb の基板に送ると戻せない）。巻き戻し防止の版番号がキーより古いものも送らない
- `fwupdate.py image <ファイル>` で、キーをつながずにファイルの版・ELF SHA-256・署名の有無を確かめられる。`info` の ELF SHA-256 は、配布 zip の `BUILDINFO.txt` と照らし合わせられる
- 更新できるのはアプリだけで、ブートローダやパーティション表は更新できない

### ワンタイムパスワード（OATH）

Google Authenticator などと同じ6桁のコード（TOTP / HOTP）を、キーの中で作れる。秘密鍵はキーの中に暗号化して保存され、PC には残らない。
キーは YubiKey と同じ OATH の仕組みを持っているが、USB の ID が違うため **Yubico Authenticator や `ykman` からは使えない**。代わりに `tools/oath.py` を使う。

```powershell
uv run --no-project --with yubikey-manager python -I tools\oath.py add            # 追加（QR コードの otpauth:// URL を貼る）
uv run --no-project --with yubikey-manager python -I tools\oath.py add --issuer GitHub --name me --touch   # 秘密鍵（Base32）で追加、タッチ必須
uv run --no-project --with yubikey-manager python -I tools\oath.py code           # 全部のコード
uv run --no-project --with yubikey-manager python -I tools\oath.py code github    # 1つだけ
uv run --no-project --with yubikey-manager python -I tools\oath.py list           # 一覧
uv run --no-project --with yubikey-manager python -I tools\oath.py delete github  # 削除
uv run --no-project --with yubikey-manager python -I tools\oath.py password set   # パスワードを付ける（clear で外す）
```

- URL や秘密鍵は、画面に表示されない入力欄で聞く（コマンドの引数には書かない。履歴に残るため）。URL は、サイトの QR コードを読み取るか、「コードを表示できない場合」などで出てくる文字列から作る
- `--touch` を付けたアカウントは、コードを出すたびに BOOT かタッチが要る（LED が青く点滅する）
- `password set` をすると、キーを挿した人がパスワードなしでコードを見られなくなる
- アカウントの名前は `code` / `delete` で一部だけ書けばよい（`github` で `GitHub:me` に当たる）
- セキュリティキーのリセット（FIDO）では消えない。消すときは `delete` で1つずつ消す

### LED の赤と緑が逆のとき

SuperMini に載っている LED は、個体によって色の順番が違う。**本人確認に成功すると赤、時間切れで緑**に見えたら、色の順番を合わせる。

```powershell
uv run --no-project --with pyscard python -I tools\fwupdate.py led-check
```

- LED を赤、続けて緑で3回ずつ点滅させ、「何色に見えたか」を聞く。答えから正しい順番を計算して設定し、最後にもう一度赤で確かめる
- 設定するときに BOOT かタッチでの本人確認が要る。設定はデータ領域に残り、ファームを更新しても消えない
- 順番がわかっていれば直接設定もできる：`led-order rgb`（標準の WS2812）、`led-order default`（既定の `grb`）。`info` で今の設定がわかる

### 困ったとき

| 症状 | 対処 |
|---|---|
| 書き込んだあと、何も光らない | 基板の **RST を押す**。書き込みツールのリセットでは、ダウンロードモードから抜けないことがある |
| RST を押しても何も光らない | アプリが起動していない（署名の拒否、ファームの破損など）。ダウンロードモードに入れずに挿したまま、COM ポート（USB シリアル）の起動ログで理由がわかる（例：`Sig block 0 signed with untrusted key`） |
| COM ポートが出てこない | ファームが動いている間は COM ポートは無い。書き込むときは BOOT を押したまま RST でダウンロードモードに入れる |
| 成功すると赤、時間切れで緑に見える | [LED の赤と緑が逆のとき](#led-の赤と緑が逆のとき) |
| 赤でゆっくり点滅する | USB のデータが通っていない。充電専用のケーブルや、電源だけの USB 口になっていないか |
| 短い PIN が断られる | PIN は8文字以上にする |
| `fwupdate.py` がファイルを送らない | キーの段階に合ったファイルか、`info` で確かめる（[ファームの更新](#ファームの更新)の表） |

## 配布バイナリの詳細

[Releases](https://github.com/alicecorecom/esp32s3-fido/releases) に、GitHub Actions（`.github/workflows/build.yml`）でビルドしたファームを置いている。

| ファイル | 中身 |
|---|---|
| `esp32s3-fido-<版>-dev.zip` | 段階 A（暗号化なし）用 |
| `esp32s3-fido-<版>-devenc.zip` | 段階 B（開発モードで暗号化）用 |
| `esp32s3-fido-<版>-devsb.zip` | 段階 B+（B ＋セキュアブート）用。作者の鍵（[`keys/`](keys/)）で署名済み |
| `esp32s3-fido-<版>-release.zip` | 段階 C（本番）用。作者の鍵で署名済み |
| `esp32s3-fido-<版>-app-sb.bin` / `-app-rel.bin` | USB 更新用の署名済みアプリ（B+ / C の基板用） |
| `esp32s3-fido-<版>-devsb-unsigned.zip` / `-release-unsigned.zip` | Actions がビルドしたままの署名なしのもの。署名済みのものを確かめるための元 |
| `SHA256SUMS` | 各ファイルの SHA-256 |

- 各 zip の `BUILDINFO.txt` に、アプリの版・巻き戻し防止の版番号・ELF SHA-256 と、各イメージの SHA-256 を書いてある
- **配布版の B+ / C を書いた基板は、作者の鍵で署名したファームしか起動しなくなる**（初回起動で `keys/` の2本の鍵を eFuse に焼く。元に戻せない）

### 本物か確かめる

Actions がビルドした zip（dev / devenc / `*-unsigned`）には、このリポジトリの Actions でビルドしたことの証明（[artifact attestation](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations)）が付いている。
[GitHub CLI](https://cli.github.com/) で確かめられる。

```powershell
gh attestation verify esp32s3-fido-<版>-devenc.zip --repo alicecorecom/esp32s3-fido
```

`Verification succeeded!` と出て、ビルドしたコミットとワークフローが表示されれば本物。

署名済みのもの（devsb / release の zip と app）は、作者が手元で署名を足したもので、Actions の証明は付いていない。
代わりに `tools/verify_release.py` で、**Actions がビルドしたもの（`*-unsigned.zip`）に署名のセクタを足しただけ**であることと、`keys/` の2本の鍵で署名されていることを確かめられる（GitHub CLI があれば `*-unsigned.zip` の証明も一緒に確かめる）。

```powershell
uv run --no-project --with esptool python -I tools\verify_release.py esp32s3-fido-<版>-devsb.zip esp32s3-fido-<版>-devsb-unsigned.zip
uv run --no-project --with esptool python -I tools\verify_release.py esp32s3-fido-<版>-app-rel.bin esp32s3-fido-<版>-release-unsigned.zip
```

最後に `OK` と出れば本物。

### ほかの書き込み方

[はじめかた](#はじめかた)は、新品の基板を2回の書き込みで本番にする手順。段階を1つずつ確かめたい場合や、以前の版で段階 A / B にした基板を進める場合は、次のように書く（zip を展開したフォルダで実行）。段階の意味は[書き込みの段階](#書き込みの段階)を参照。

```powershell
# A. dev / B. devenc の初回
uvx esptool --chip esp32s3 -p COMx write-flash "@flash_args"
# B. devenc の2回目以降
uvx esptool --chip esp32s3 -p COMx write-flash "@encrypted_flash_args"
# B+. devsb（B を通った基板に。初回起動で作者の鍵を eFuse に焼く。元に戻せない）
uvx esptool --chip esp32s3 -p COMx --no-stub write-flash "@encrypted_flash_args"
# C. release（B+ を通った基板に。元に戻せない）
uvx esptool --chip esp32s3 -p COMx --no-stub write-flash --force "@encrypted_flash_args"
```

- 各段階で「PIN 設定 → 登録 → **抜き差し** → ログイン」まで確かめてから次へ進む。A を書いたら最初に `led-check` をしておく
- B+ と C の前に `get-security-info` で基板の状態を確かめる。B を通った基板の B+ の前は `SPI_BOOT_CRYPT_CNT` が `0x1` で `Secure Boot: Disabled`、C の前は `0x1` で `Secure Boot: Enabled`。`idf.ps1` はこれを自動で確かめるが、esptool は確かめない
- セキュアブートが有効な基板では、esptool はブートローダの領域に書くのを `--force` なしでは拒む（署名の合わないブートローダを書くと起動しなくなるため）。`--force` は、その基板に焼いた鍵で署名済みのものを書くときだけ付ける
- 新品に release を直接書くこともできる仕組みだが、**実機で確かめていない**。失敗すると基板は二度と書き直せないので、[はじめかた](#はじめかた)のとおり B+ を通す

### 配布物の作り方（作者向け）

1. `v*` のタグを push すると、Actions が4つのプロファイルをビルドし、証明を付けて Release の下書きを作る
2. 手元で `tools/sign_release.py --tag <タグ> --upload` を実行する。下書きの `*-unsigned.zip` の証明を確かめ、1Password の鍵で署名し、`verify_release.py` と同じ確認を通してから、署名済みの zip と app を下書きに足す
3. 下書きの中身を確かめてから公開する

## 自分でビルドする

自分の鍵でセキュアブートを有効にしたい場合や、改造を加えたい場合は、ESP-IDF でビルドして書き込む。

### 準備

- **ESP-IDF v5.5.4**（pico-fido 公式ビルドと同じ版）
- Windows + PowerShell（`idf.ps1` は PowerShell 用。Git Bash などの MSys 環境では ESP-IDF のツールが動かない）

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

### ビルド

```powershell
git submodule update --init --recursive
git -C pico-fido apply ../patches/pico-fido-esp32s3.patch
git -C pico-fido/pico-keys-sdk apply ../../patches/pico-keys-sdk-esp32s3.patch
Copy-Item config\dependencies.lock pico-fido\   # ESP-IDF コンポーネントの版を固定

.\idf.ps1 dev build          # 暗号化なし            -> build\dev
.\idf.ps1 devenc build       # 開発モードで暗号化    -> build\devenc
.\idf.ps1 devsb build        # devenc＋セキュアブート -> build\devsb（署名なし。署名は書き込み時）
.\idf.ps1 release build      # release（本番）       -> build\release
.\check_no_radio.ps1         # 無線のコードが無いことを確認
```

- `idf.ps1` は、`export.ps1` を使わずに環境変数を設定して `idf.py` を呼ぶラッパー。2番目以降の引数は `idf.py` にそのまま渡す
- sdkconfig は、pico-keys-sdk の defaults → `config/sdkconfig.common` → `config/sdkconfig.<profile>` の順に重ねる
- パーティションテーブルは全プロファイル共通で 0x10000 に置く（暗号化入りのブートローダは 0x80C0 バイトあり、標準の 0x8000 では収まらない）
- パーティションは `config/partitions.csv`：アプリ領域 ota_0（0x20000）と ota_1（0x300000）の2面、データ領域 part0 は本家と同じ 0x200000。1面（factory）の版から書き直しても、登録済みのパスキーは残る

### 書き込みの段階

> [!CAUTION]
> eFuse の書き込みとフラッシュ暗号化は **元に戻せません。** A → B → B+ → C の順に進め（新品の基板は[一発で B+](#新品の基板は一発で-b-から) から始められる）、
> 各段階で「PIN 設定 → 登録 → **抜き差し** → ログイン」まで確認してから次へ進んでください。

| 段階 | コマンド | 何が起きるか | 戻せるか |
|---|---|---|---|
| A. dev | `.\idf.ps1 dev -p COMx flash` | 初回起動で eFuse KEY3 を焼く | ファームは書き直せる |
| B. devenc | 初回：`.\idf.ps1 devenc -p COMx flash`<br>以降：`.\idf.ps1 devenc -p COMx encrypted-flash` | 初回起動でブートローダがフラッシュを暗号化する（開発モード） | 暗号化は解除できないが、`encrypted-flash` で書き直せる |
| B+. devsb | `.\idf.ps1 devsb -p COMx encrypted-flash` | B に加えて、初回起動でブートローダがセキュアブートを有効にする（[下記](#セキュアブートdevsb)） | **セキュアブートは解除できない。** 登録した鍵で署名すれば書き直せる |
| C. release | `.\idf.ps1 release -p COMx encrypted-flash` | B+ と同じ鍵で署名して書く。起動時にアプリが release モードへ切り替え、secure download mode を有効にする | **戻せない。** ブートローダは二度と変えられない。アプリは [USB 経由の更新](#ファームの更新) でしか変えられない |

- 書き込むと USB が FIDO2 デバイスに切り替わり、COM ポートは消える。書き直すときは **BOOT を押しながら RST** を押してダウンロードモードに入れる
- 書き込んだあとは **基板の RST だけを押して** 起動する。USB 経由のリセットでは、手で入れたダウンロードモードから抜けられない
- B の間は盗難対策にならない（他人が自分のファームを書き込み、HMAC 回路を使える。フラッシュを吸い出して書き戻せば PIN の失敗回数も戻せる）。大事なアカウントは C の後に登録する
- C の後は、試験中の登録を消すため Windows の「セキュリティ キーのリセット」をする（親鍵も作り直される）
- `idf.ps1 release` は、開発モードで暗号化済み **かつ** セキュアブートが有効な基板（B+ を通ったもの）にしか書かない（新品の基板を除く。下記）。`$env:ESP32S3_FIDO_RELEASE_OK = 'yes'` と、devsb と同じ `$env:ESP32S3_FIDO_SB_VAULT` / `$env:ESP32S3_FIDO_SB_KEYS` が要る
- 自分でビルドしたアプリの USB 更新には、`idf.ps1 devsb` / `release` の書き込みで `build\<profile>\signed\` にできる署名済みの `pico_fido.bin` を送る

### 新品の基板は一発で B+ から

v0.1.3 以降、何も書いていない新品の基板（暗号化もセキュアブートも無効、eFuse の鍵ブロックが全部空）には、A と B を飛ばして **B+ を1回書くだけ** で済む。

1. 新品に devsb を書く（暗号化せずに書く。`idf.ps1 devsb` は新品を見分けて自動でそうする。配布版なら署名済み `devsb.zip` の `flash_args`）
2. RST を押すと、最初の起動でブートローダがセキュアブートとフラッシュ暗号化（開発モード）を有効にし、フラッシュを暗号化する（十数秒）。続いてアプリが HMAC の鍵を焼き、最後に `WR_DIS_RD_DIS` を焼く
3. PIN 設定 → 登録 → 抜き差し → ログインと、`led-check` を確かめる
4. 問題がなければ、通常どおり C（release）を書く

- 試験済み：新品から一発で B+ にした基板の eFuse の保護の状態（鍵の読み取り禁止、`WR_DIS_RD_DIS`、鍵の失効）は、段階を踏んで B+ にした基板と同じになった
- 仕組みとしては、新品に **release を直接**書くこともできる（最初の起動で release モードの暗号化と secure download mode まで進む）。ただし **この経路は実機で確かめていない**。失敗すると基板は二度と書き直せないので、確かめるまでは上の手順（一発で B+ → C）を使う
- ブートローダには、ロールバック（更新したアプリが USB の接続まで行けなければ、次の起動で前の面に戻す）と巻き戻し防止（`config/sdkconfig.common` の `CONFIG_BOOTLOADER_APP_SECURE_VERSION` より古いアプリを起動しない）を入れてある。C の後はブートローダを変えられないので、この2つは C の前に入っている必要がある
- `SECURE_VERSION` を上げるのは、古い版を使わせたくない脆弱性を直したときだけ。上げた版が起動すると eFuse に焼かれ、上げられるのは全部で16回

### セキュアブート（devsb）

自分の署名鍵（RSA-3072、最大3本）で署名したブートローダとアプリしか起動しないようにする。

- 鍵は 1Password に「ドキュメント」（PEM）として置く。`tools/sbsign.py` が `op document get` でメモリに読んで署名し、ディスクには書かない。署名のたびに 1Password の認証が要る
- 初回起動で、ブートローダに付けた署名の数だけ eFuse の鍵枠（KEY0〜5 の空き）に公開鍵のダイジェストを焼き、残りの枠は失効させる。予備鍵も最初から付けておくこと（あとから足せない）
- あわせて JTAG の無効化と `WR_DIS_RD_DIS`（以後、読み取り禁止の鍵を足せない）も焼く
- フラッシュ暗号化は開発モードのまま、ダウンロードモードも開いたまま。登録した鍵で署名すれば何度でも書き直せる。**鍵を失くすと二度と書き換えられない**

```powershell
$env:ESP32S3_FIDO_SB_VAULT = '<1Password の保管庫>'
$env:ESP32S3_FIDO_SB_KEYS  = '<本鍵>;<予備鍵>'    # 1Password のドキュメント名か ID。この順に鍵枠へ焼かれる
$env:ESP32S3_FIDO_SB_OK    = 'yes'                # セキュアブートがまだ無効の基板に書くときだけ要る（1回ごとに消える）
.\idf.ps1 devsb -p COMx encrypted-flash
```

- `idf.ps1` は、基板の状態を確かめ、ビルドし、ブートローダとアプリに全部の鍵で署名して検証してから書き込む
- セキュアブートを有効にした構成では、ESP-IDF の `flash_args` にブートローダが入らない（`bootloader-flash_args` に分かれる）。`idf.ps1` は両方を合わせて書く

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
- キーが名乗っている値は `tools/ccid/getinfo.py` で確認できる（CCID 経由。管理者権限は要らない）

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
- 理由は[PIN は8桁以上にする](#pin-は8文字以上にする)を参照（フラッシュの書き戻しで失敗回数が戻る攻撃）
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

物理的に盗まれたキーを専門の装置で解析されることへの耐性は、市販のセキュリティキーに及ばない（冒頭の注意を参照）。

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
- このリポジトリで新しく書いたもの（`idf.ps1`、`check_no_radio.ps1`、`config/`、`ci/`、`.github/`、`keys/`、`tools/sbsign.py`、`tools/fwupdate.py`、`tools/oath.py`、`tools/sign_release.py`、`tools/verify_release.py`、`tools/touchprobe/`、パッチで追加する `touch_button.c/.h`・`fw_update.c`）は Copyright (c) 2026 Alice Core、AGPL-3.0-only
- ESP-IDF（Apache-2.0）、TinyUSB（MIT）、Mbed TLS（Apache-2.0）などは、それぞれのライセンスに従う

ファームを書き込んだキーを人に渡す場合は、対応するソース（このリポジトリと、ビルドに使ったコミット）を入手できるようにしてください。
