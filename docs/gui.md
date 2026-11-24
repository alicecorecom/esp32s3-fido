[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# 管理ツール（GUI）

キーの状態の確認と、設定できることの全部を、1つのウィンドウで行える（`tools/gui/`、PyQt6）。

- **Windows**：[Releases](https://github.com/alicecorecom/esp32s3-fido/releases/latest) の `esp32s3-fido-manager-<版>.exe` をダウンロードして起動する（インストール不要）。コード署名はしていないので、初回は SmartScreen の「詳細情報 → 実行」が要る。本物かどうかは `gh attestation verify esp32s3-fido-manager-<版>.exe --repo alicecorecom/esp32s3-fido` で確かめられる
- **macOS / Linux、またはソースから**：リポジトリのフォルダで uv から起動する

```powershell
uv run --project tools\gui python -I tools\gui\app.py
```

| タブ | できること |
|---|---|
| 状態 | ファームの版・段階・セキュアブート・暗号化、PIN の残り回数、シリアル番号 |
| パスキー（FIDO2） | PIN の設定・変更、キーに保存されたパスキーの一覧・削除、「常に本人確認」、PIN の最短の長さ、リセット |
| ワンタイムパスワード | コードの一覧（ダブルクリックでコピー）、追加・名前の変更・削除、パスワード（[下記](usage.md#ワンタイムパスワードoath)と同じ） |
| OTP スロット | BOOT を押すと打つ内容（静的パスワード・HOTP）、チャレンジレスポンス（HMAC-SHA1） |
| ファーム | USB 経由の更新、LED の色合わせ・色順、再起動 |
| キーを作る | 新品の基板に配布版を書き込む（[はじめかた](getting-started.md#はじめかた)の 1〜4 と同じ流れ）。最新版のダウンロードと本物かの確認、基板の状態の判定、B+ と C の書き込み |

- スマートカード（CCID）経由で話す。キーは挿し替えると自動で切り替わる
- **Windows では、「パスキー（FIDO2）」タブだけ管理者権限が要る**（Windows は、ブラウザと Windows 以外のアプリに FIDO を直接扱わせない。スマートカード経由でも同じ）。タブの「管理者として起動し直す」で UAC の確認を経て開き直す。ほかのタブは管理者権限なしで使える
- BOOT / タッチを待つときは、ウィンドウの右下に案内が出る
- パスキーの一覧に出るのは、キーの中に保存されるもの（discoverable credential）だけ。サイトによっては、キーに保存しない形で登録する（ログインはできるが一覧には出ない）
- 依存パッケージの版は `tools/gui/pyproject.toml` と `uv.lock` で固定している
