[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# 配布バイナリの詳細

[Releases](https://github.com/alicecorecom/esp32s3-fido/releases) に、GitHub Actions（`.github/workflows/build.yml`）でビルドしたファームを置いている。

| ファイル | 中身 |
|---|---|
| `esp32s3-fido-<版>-dev.zip` | 段階 A（暗号化なし）用 |
| `esp32s3-fido-<版>-devenc.zip` | 段階 B（開発モードで暗号化）用 |
| `esp32s3-fido-<版>-devsb.zip` | 段階 B+（B ＋セキュアブート）用。作者の鍵（[`keys/`](../keys/)）で署名済み |
| `esp32s3-fido-<版>-release.zip` | 段階 C（本番）用。作者の鍵で署名済み |
| `esp32s3-fido-<版>-app-sb.bin` / `-app-rel.bin` | USB 更新用の署名済みアプリ（B+ / C の基板用） |
| `esp32s3-fido-manager-<版>.exe` | Windows 用の[管理ツール（GUI）](gui.md#管理ツールgui)。Actions でビルドし、証明付き |
| `esp32s3-fido-<版>-devsb-unsigned.zip` / `-release-unsigned.zip` | Actions がビルドしたままの署名なしのもの。署名済みのものを確かめるための元 |
| `SHA256SUMS` | 各ファイルの SHA-256 |

- 各 zip の `BUILDINFO.txt` に、アプリの版・巻き戻し防止の版番号・ELF SHA-256 と、各イメージの SHA-256 を書いてある
- **配布版の B+ / C を書いた基板は、作者の鍵で署名したファームしか起動しなくなる**（初回起動で `keys/` の2本の鍵を eFuse に焼く。元に戻せない）

## 本物か確かめる

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

## ほかの書き込み方

[はじめかた](getting-started.md#はじめかた)は、新品の基板を2回の書き込みで本番にする手順。段階を1つずつ確かめたい場合や、以前の版で段階 A / B にした基板を進める場合は、次のように書く（zip を展開したフォルダで実行）。段階の意味は[書き込みの段階](building.md#書き込みの段階)を参照。

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
- 新品に release を直接書くこともできる仕組みだが、**実機で確かめていない**。失敗すると基板は二度と書き直せないので、[はじめかた](getting-started.md#はじめかた)のとおり B+ を通す

## 配布物の作り方（作者向け）

1. `v*` のタグを push すると、Actions が4つのプロファイルをビルドし、証明を付けて Release の下書きを作る
2. 手元で `tools/sign_release.py --tag <タグ> --upload` を実行する。下書きの `*-unsigned.zip` の証明を確かめ、1Password の鍵で署名し、`verify_release.py` と同じ確認を通してから、署名済みの zip と app を下書きに足す
3. リリースノート（`ci/release-notes.md` の雛形から作られる）の「新しいもの」を書き、先頭の作者向けの NOTE を消す
4. 下書きの中身を確かめてから公開する
