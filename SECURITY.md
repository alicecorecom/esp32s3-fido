# セキュリティ

## 脆弱性の報告

脆弱性を見つけた場合は、公開の Issue には書かず、
[Security タブの「Report a vulnerability」](https://github.com/alicecorecom/esp32s3-fido/security/advisories/new)から非公開で報告してください。

報告には、再現の手順と、影響を受けるビルドのプロファイル（dev / devenc / release）があると助かります。

## 対象

- このリポジトリの改造部分（`patches/` の2つのパッチ、`idf.ps1`、`config/`、`tools/`）

## 対象外

- 改造していない pico-fido / pico-keys-sdk 本体の問題は、[本家](https://github.com/polhenarejos/pico-fido)に報告してください
- README の冒頭に書いているハードウェアの限界（専用のセキュリティチップが無いこと、グリッチ攻撃などへの耐性）
