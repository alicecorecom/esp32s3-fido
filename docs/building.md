[← README](../README.md) ・ [はじめかた](getting-started.md) ・ [使い方](usage.md) ・ [管理ツール](gui.md) ・ [配布バイナリ](releases.md) ・ [ビルド](building.md) ・ [改造の詳細](internals.md)

# 自分でビルドする

自分の鍵でセキュアブートを有効にしたい場合や、改造を加えたい場合は、ESP-IDF でビルドして書き込む。

## 準備

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

## ビルド

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

## 書き込みの段階

> [!CAUTION]
> eFuse の書き込みとフラッシュ暗号化は **元に戻せません。** A → B → B+ → C の順に進め（新品の基板は[一発で B+](#新品の基板は一発で-b-から) から始められる）、
> 各段階で「PIN 設定 → 登録 → **抜き差し** → ログイン」まで確認してから次へ進んでください。

| 段階 | コマンド | 何が起きるか | 戻せるか |
|---|---|---|---|
| A. dev | `.\idf.ps1 dev -p COMx flash` | 初回起動で eFuse KEY3 を焼く | ファームは書き直せる |
| B. devenc | 初回：`.\idf.ps1 devenc -p COMx flash`<br>以降：`.\idf.ps1 devenc -p COMx encrypted-flash` | 初回起動でブートローダがフラッシュを暗号化する（開発モード） | 暗号化は解除できないが、`encrypted-flash` で書き直せる |
| B+. devsb | `.\idf.ps1 devsb -p COMx encrypted-flash` | B に加えて、初回起動でブートローダがセキュアブートを有効にする（[下記](#セキュアブートdevsb)） | **セキュアブートは解除できない。** 登録した鍵で署名すれば書き直せる |
| C. release | `.\idf.ps1 release -p COMx encrypted-flash` | B+ と同じ鍵で署名して書く。起動時にアプリが release モードへ切り替え、secure download mode を有効にする | **戻せない。** ブートローダは二度と変えられない。アプリは [USB 経由の更新](usage.md#ファームの更新) でしか変えられない |

- 書き込むと USB が FIDO2 デバイスに切り替わり、COM ポートは消える。書き直すときは **BOOT を押しながら RST** を押してダウンロードモードに入れる
- 書き込んだあとは **基板の RST だけを押して** 起動する。USB 経由のリセットでは、手で入れたダウンロードモードから抜けられない
- B の間は盗難対策にならない（他人が自分のファームを書き込み、HMAC 回路を使える。フラッシュを吸い出して書き戻せば PIN の失敗回数も戻せる）。大事なアカウントは C の後に登録する
- C の後は、試験中の登録を消すため Windows の「セキュリティ キーのリセット」をする（親鍵も作り直される）
- `idf.ps1 release` は、開発モードで暗号化済み **かつ** セキュアブートが有効な基板（B+ を通ったもの）にしか書かない（新品の基板を除く。下記）。`$env:ESP32S3_FIDO_RELEASE_OK = 'yes'` と、devsb と同じ `$env:ESP32S3_FIDO_SB_VAULT` / `$env:ESP32S3_FIDO_SB_KEYS` が要る
- 自分でビルドしたアプリの USB 更新には、`idf.ps1 devsb` / `release` の書き込みで `build\<profile>\signed\` にできる署名済みの `pico_fido.bin` を送る

## 新品の基板は一発で B+ から

v0.1.3 以降、何も書いていない新品の基板（暗号化もセキュアブートも無効、eFuse の鍵ブロックが全部空）には、A と B を飛ばして **B+ を1回書くだけ** で済む。

1. 新品に devsb を書く（暗号化せずに書く。`idf.ps1 devsb` は新品を見分けて自動でそうする。配布版なら署名済み `devsb.zip` の `flash_args`）
2. RST を押すと、最初の起動でブートローダがセキュアブートとフラッシュ暗号化（開発モード）を有効にし、フラッシュを暗号化する（十数秒）。続いてアプリが HMAC の鍵を焼き、最後に `WR_DIS_RD_DIS` を焼く
3. PIN 設定 → 登録 → 抜き差し → ログインと、`led-check` を確かめる
4. 問題がなければ、通常どおり C（release）を書く

- 試験済み：新品から一発で B+ にした基板の eFuse の保護の状態（鍵の読み取り禁止、`WR_DIS_RD_DIS`、鍵の失効）は、段階を踏んで B+ にした基板と同じになった
- 仕組みとしては、新品に **release を直接**書くこともできる（最初の起動で release モードの暗号化と secure download mode まで進む）。ただし **この経路は実機で確かめていない**。失敗すると基板は二度と書き直せないので、確かめるまでは上の手順（一発で B+ → C）を使う
- ブートローダには、ロールバック（更新したアプリが USB の接続まで行けなければ、次の起動で前の面に戻す）と巻き戻し防止（`config/sdkconfig.common` の `CONFIG_BOOTLOADER_APP_SECURE_VERSION` より古いアプリを起動しない）を入れてある。C の後はブートローダを変えられないので、この2つは C の前に入っている必要がある
- `SECURE_VERSION` を上げるのは、古い版を使わせたくない脆弱性を直したときだけ。上げた版が起動すると eFuse に焼かれ、上げられるのは全部で16回

## セキュアブート（devsb）

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
