> [!NOTE]
> 作者向け（公開前に消す）：`tools/sign_release.py --tag {TAG} --upload` で署名済みの devsb / release と更新用のアプリを足し、「新しいもの」を書いてから公開する。

## 新しいもの

- （ここに書く）

## ファイル

| ファイル | 使いみち |
|---|---|
| `esp32s3-fido-manager-{TAG}.exe` | 管理ツール（Windows）。新品の基板への書き込み、パスキー・PIN、ワンタイムパスワード、ファームの更新 |
| `esp32s3-fido-{TAG}-devsb.zip` / `-release.zip` | 新品の基板に書くファーム（作者の鍵で署名済み） |
| `esp32s3-fido-{TAG}-app-rel.bin` / `-app-sb.bin` | 使っているキーの更新用（C / B+ の基板） |
| `*-unsigned.zip`、`dev.zip`、`devenc.zip` | 確認用と、段階を踏んで書く場合 |

## 確かめ方

- exe と zip には GitHub Actions の証明が付いている：`gh attestation verify <ファイル> --repo alicecorecom/esp32s3-fido`
- 署名済みのものは `tools/verify_release.py` で確かめられる（[docs/releases.md](https://github.com/alicecorecom/esp32s3-fido/blob/{TAG}/docs/releases.md)）
- exe はコード署名をしていないので、初回は SmartScreen の「詳細情報 → 実行」が要る

> [!WARNING]
> サブの鍵・学習用です。専用のセキュリティチップが無く、物理的な攻撃への耐性は市販のセキュリティキーに及びません。
