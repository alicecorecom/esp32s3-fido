[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# 使い方

## 本人確認

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

## PIN は8文字以上にする

PIN は **8文字以上**（英字や記号も混ぜられる。最大63バイト）にする。キーは間違いを8回で締め出すが、それだけに頼れないため。
ファームも8文字未満の PIN を断る（Windows では「もう少し複雑な PIN にしてください」と出る）。この制限の前に設定した短い PIN はそのまま使えるので、PIN の変更で8文字以上にしておく。

- フラッシュを丸ごと吸い出して後で書き戻すと、PIN の失敗回数も元に戻る（[Token2 の勧告](https://www.token2.com/img/T2-SA-RP2350-Dec2025.pdf)、pico-fido 共通）。これを繰り返せば PIN を総当たりできる
- 勧告の見積もりでは、総当たりにかかる時間は **4桁で約8時間、6桁で約34日、8桁で約10年**
- esp32s3-fido では、ダウンロードモードが開いている段階（dev / devenc / devsb）の間はこの吸い出しと書き戻しができる。本番の段階（release）ではダウンロードモードでフラッシュを読めず、フラッシュもチップに内蔵なので、かなり難しくなる
- PIN の保存方法の弱さ（吸い出したデータから PIN を割り出せた）は、pico-fido の commit 6c85421 で直っていて、v8.2 に入っている

## ファームの更新

挿したまま USB で更新できる（ダウンロードモードも管理者権限も要らない）。登録済みのパスキーと PIN はそのまま残る。

1. [Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) から、キーの段階に合ったアプリをダウンロードする。[はじめかた](getting-started.md#はじめかた)のとおりに書いたキーなら `esp32s3-fido-<版>-app-rel.bin`
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

## ワンタイムパスワード（OATH）

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

## LED の赤と緑が逆のとき

SuperMini に載っている LED は、個体によって色の順番が違う。**本人確認に成功すると赤、時間切れで緑**に見えたら、色の順番を合わせる。

```powershell
uv run --no-project --with pyscard python -I tools\fwupdate.py led-check
```

- LED を赤、続けて緑で3回ずつ点滅させ、「何色に見えたか」を聞く。答えから正しい順番を計算して設定し、最後にもう一度赤で確かめる
- 設定するときに BOOT かタッチでの本人確認が要る。設定はデータ領域に残り、ファームを更新しても消えない
- 順番がわかっていれば直接設定もできる：`led-order rgb`（標準の WS2812）、`led-order default`（既定の `grb`）。`info` で今の設定がわかる

## 困ったとき

| 症状 | 対処 |
|---|---|
| 書き込んだあと、何も光らない | 基板の **RST を押す**。書き込みツールのリセットでは、ダウンロードモードから抜けないことがある |
| RST を押しても何も光らない | アプリが起動していない（署名の拒否、ファームの破損など）。ダウンロードモードに入れずに挿したまま、COM ポート（USB シリアル）の起動ログで理由がわかる（例：`Sig block 0 signed with untrusted key`） |
| COM ポートが出てこない | ファームが動いている間は COM ポートは無い。書き込むときは BOOT を押したまま RST でダウンロードモードに入れる |
| 成功すると赤、時間切れで緑に見える | [LED の赤と緑が逆のとき](#led-の赤と緑が逆のとき) |
| 赤でゆっくり点滅する | USB のデータが通っていない。充電専用のケーブルや、電源だけの USB 口になっていないか |
| 短い PIN が断られる | PIN は8文字以上にする |
| `fwupdate.py` がファイルを送らない | キーの段階に合ったファイルか、`info` で確かめる（[ファームの更新](#ファームの更新)の表） |
