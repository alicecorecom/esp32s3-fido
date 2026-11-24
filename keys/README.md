# Secure Boot の公開鍵

配布する devsb / release のファーム（ブートローダとアプリ）は、この2本の鍵（RSA-3072）で署名している。
秘密鍵は作者の 1Password にあり、このリポジトリにも CI にも置かない。

| ファイル | 役割 | eFuse に焼かれるダイジェスト（SHA-256） |
|---|---|---|
| `sb-key-1-primary.pub.pem` | 本鍵 | `de 92 d4 cf 4a b6 80 f4 52 6c 83 65 cf 6e a6 dd 30 03 1b 79 55 dd 2b ca 18 69 53 a8 e7 45 56 0a` |
| `sb-key-2-backup.pub.pem` | 予備鍵（本鍵が漏れたときに使う） | `13 43 47 ff c3 e1 75 9b 7e 97 b5 e6 8a 14 b9 b8 6a 59 b2 62 d3 de 22 6d f6 d3 96 7b b4 a5 6f 47` |

- 配布版の devsb を書いた基板は、初回起動でこの2本のダイジェストを eFuse の KEY1・KEY2 に焼き、以後この2本で署名したファームしか起動しない
- 基板に焼かれた値は `espefuse summary`（devsb の間）の `BLOCK_KEY1` / `BLOCK_KEY2` で確かめられる
- 配布物の署名の確かめ方は、トップの README の「配布バイナリ」を参照（`tools/verify_release.py`）
- 自分の鍵を使いたい場合は、配布版の devsb / release を使わず、自分でビルドして `idf.ps1 devsb` で書く
