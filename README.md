# py-youtube-transcript-api

[GitHub: sinzy0925/py_youtube-transcript-api](https://github.com/sinzy0925/py_youtube-transcript-api)

YouTube の動画を指定すると、**字幕を取得し、Gemini で要約し（真実度の目安の付与可）、必要なら Gmail で結果を受け取る**までを、ターミナルからまとめて実行するスクリプト群です（ブラウザ上の GUI アプリというより **CLI 向けツールキット**）。

中身の処理は **字幕取得**（[sinzy0925/youtube-transcript-api](https://github.com/sinzy0925/youtube-transcript-api)）→ **Gemini による要約** → **Gmail 送信**です。API キーは複数本ローテーションする `m03_api_key_manager` に対応します。

### よくある使い方（3 パターン）

1. **1 本だけ** … Cloud Shell などで `.env` を用意したうえで、`./run_pipeline.sh 'https://youtu.be/…'` を実行すると、**要約などがメールで届く**（`MAIL_TO` / `TO_EMAIL` と Gmail 送信設定がある場合。無ければ `--skip-email` 相当でファイルのみ）。
2. **URL を複数** … `urls.txt` に **1 行 1 URL**（`#` 始まりと空行は無視）で書き、`./run_pipeline_urls.sh` または `./run_pipeline_urls.sh /path/to/urls.txt` で **上から順に** `run_pipeline.sh` が走り、**それぞれメールで届く**（起動間隔は `URLS_PIPELINE_GAP_SEC`、既定 65 秒）。`BUILD_HTML_SITE=1` なら **全件のキュー完了後に `docs/` を1回生成**（後述）。
3. **チャンネル単位** … `./run_channel.sh --fromto 0:10 --url 'https://www.youtube.com/@…'` のように **`--fromto` で範囲**を指定すると、その範囲の動画を **順番に**要約パイプラインへ回す（`b01` はチャンネル「動画」タブ相当の **先頭を 0** とした添字で、**多くのチャンネルでは新しい動画が上のため 0 が最新側**。範囲は両端含む。例 `0:10` は 11 本）。
4. **要約を Web 公開** … `output/` の要約から **`docs/`** に静的 HTML を生成し、**GitHub Pages** で公開（`build_html_site.py` / `BUILD_HTML_SITE=1`）。後述。

**Google Cloud Shell**（Google アカウントがあれば無料枠で使える）で動かす手順を下にまとめています。ローカルは **Git Bash / WSL / Linux** などの Bash が使える環境を想定しています。

## Cloud Shell（スマホの Google Cloud アプリ等）: URL だけ貼りやすくする（任意）

スマホの **Google Cloud** アプリから Cloud Shell を開き、`./run_pipeline.sh "https://youtu.be/…"` のように **コマンドと引用符で URL を囲む形**を一度に貼るのは、メモ帳などで **`./run_pipeline.sh` と `"https://…"` を組み立てる**必要があり面倒です。

その場合、Cloud Shell の **Bash にエイリアス**を登録すると、**先に `./run_pipeline.sh "` までを固定し、あとから URL を貼る**流れにできます（毎回、リポジトリ直下に **`cd` してから**使ってください。例: `cd ~/py_youtube-transcript-api` や `junbi.sh` で作った作業ディレクトリ）。

1. `nano ~/.bashrc` でファイルを開く。
2. 次の 1 行を追記する（行末の `"` は **開きっぱなし**で、URL を後から閉じるためです）。

```bash
alias aa='./run_pipeline.sh "'
```

3. **Ctrl+O**（保存）→ **Enter** → **Ctrl+X**（nano を終了）。
4. `source ~/.bashrc` で反映。

以降、リポジトリ直下に `cd` したうえで **`aa` と入力して Enter** すると、シェルが **`>`** の継続プロンプトを出すので、そこに **YouTube からコピーした URL を貼り付け**、**最後に半角の `"` を付けて** Enter すれば実行されます。

**改善される点:** メモなどでコマンドと引用符を毎回組み立てる手間を減らせます。

## Google Cloud Shell でのクイックスタート


[Google Cloud Shell](https://cloud.google.com/shell) のターミナルに次の 1 行を貼り付けて実行すると、リポジトリの取得と `junbi.sh`（パイプライン用シェルへの実行権限付与・ホーム直下へのシンボリックリンク作成）までのセットアップができます。

```bash
mkdir -p py_youtube-transcript-api && curl -fsSL https://github.com/sinzy0925/py_youtube-transcript-api/archive/refs/heads/main.tar.gz | tar xz --strip-components=1 -C py_youtube-transcript-api && cd py_youtube-transcript-api && chmod +x junbi.sh && bash junbi.sh
```

続けてリポジトリ直下の **`.env`** を編集すれば実行できます（なければ `.env.sample` をコピーして作成。変数の例は後述の「`.env` に最低限書くもの」を参照）。例: `./run_pipeline.sh 'https://www.youtube.com/watch?v=…'`。初回実行時に `run_pipeline.sh` が仮想環境（`.venv`）の作成と `pip install -r requirements.txt` を行います。

### Cloud Shell: 字幕の IP ブロック時に再起動を案内する（任意）

`.env` に **`CLOUDSHELL_REBOOT_ON_YOUTUBE_IP_BLOCK=1`** を書くと、`a05` が **YouTube の IP ブロック系**（`RequestBlocked` / `IpBlocked` や「blocking requests from your IP」など）で字幕取得に失敗した直後、ログに **`[Cloud Shell 再起動案内]`** を出し、**手動で Restart Cloud Shell する手順**を表示します。

- **自動で `sudo reboot` は行いません。** Cloud Shell は systemd が PID 1 ではないコンテナのため、`sudo reboot` は *System has not been booted with systemd…* で失敗します。公式の **Restart Cloud Shell**（歯車メニュー）が確実です。
- **`DEVSHELL_PROJECT_ID` 等が無い環境では案内を出しません**（ローカル実行でのノイズ防止）。

## 必要環境

- **Python 3.10+**（3.12 / 3.13 で動作確認想定）
- インターネット接続
- 字幕: `youtube_transcript_api` 利用時、一部クラウド / 共有 IP では [YouTube 側制限](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)で取得に失敗する場合あり
- 要約: **Google AI Studio / Gemini** 用の API キー（`GOOGLE_API_KEY` や `GOOGLE_API_KEY_1` … または `.env`）
- メール（任意）: **Gmail** のアドレス＋[アプリパスワード](https://support.google.com/accounts/answer/185833)

## セットアップ

```bash
cd py_youtube-transcript-api
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
```

リポジトリルートに **`.env`** を置き、キー類を記載します。`.env` は **`.gitignore` 済み**（コミットしないでください）。  
任意で `a05` が `load_dotenv()` するため、プロジェクト直下の `.env` を読みます。`m03_api_key_manager` も同パスの `.env` を参照します。

### `.env` に最低限書くもの（メール送信まで行う場合）

**要約＋Gmail 送信まで**回すときの目安です。値はすべて実物に置き換えてください。

```env
GOOGLE_API_KEY="あなたのAPIキー"
TRUTH_ASSESSMENT_GROUNDING=1
TO_EMAIL="あなたのメルアド"
GMAIL_USER="送信元のメルアド"
GMAIL_APP_PASSWORD="送信元のGmailのアプリパスワード"
```

以下の様にしておくと、１つのキーが失敗した際に、次のキーを活用して処理が成功する可能性が上がります。
キーは別々に準備してください。
```env
GOOGLE_API_KEY_1="あなたのAPIキー1"
GOOGLE_API_KEY_2="あなたのAPIキー2"
GOOGLE_API_KEY_3="あなたのAPIキー3"
```

`GOOGLE_API_KEY_1` を**1つでも**設定すると、Gemini は**番号付きキーのローテーションだけ**を使います。その場合、未番号の **`GOOGLE_API_KEY` は Gemini には使われません**（番号側を環境から外せば未番号へフォールバック）。複数本命にするなら上のように `_1,_2,...` に揃えるのが安全です。

- **`GOOGLE_API_KEY`**: [Google AI Studio](https://aistudio.google.com/) 等で発行した **Gemini 用 API キー**。
- **`TRUTH_ASSESSMENT_GROUNDING`**: `1` で真実度（目安）の検索グラウンディングを利用（`0` でオフ。未設定でも既定は ON 扱い）。
- **`TO_EMAIL`**: 成果物を送る**宛先**。代わりに **`MAIL_TO`** でも可（どちらかがあれば `run_pipeline.sh` はメール送信ルート）。
- **`GMAIL_USER`**: 送信に使う **Gmail アドレス**（通常は `@gmail.com` まで含む全文）。
- **`GMAIL_APP_PASSWORD`**: そのアカウントの **[アプリパスワード](https://support.google.com/accounts/answer/185833)**（**16 文字**。2 段階認証有効時に発行。**通常のログインパスワードではない**）。

**`.env` に書くときの注意（アプリパスワード）**: Google の画面から **そのままコピー＆ペースト**すると、見た目は半角スペースでも **ノンブレークスペース（U+00A0）** が区切りに混ざることがあります。SMTP まわりで **`ascii` エンコードエラー**などの原因になり得るので、**16 文字を手入力する**か、**メモ帳などプレーンテキストに一度貼り、区切りを通常の半角スペースに直す／スペースを消して 16 文字連続にしてから** `.env` に貼ると安全です。値は `GMAIL_APP_PASSWORD="..."` のように **引用符で囲む**とよいです（中身に NBSP が残っていると問題は解消しないので、**中身の文字種**が重要です）。

**メール不要**（字幕・要約ファイルだけ）のときは、`TO_EMAIL` / `MAIL_TO` を空にするか省略し、`python a05_... --skip-email` を使うか、`run_pipeline.sh` だけ使うと自動で `--skip-email` されます。最低限は **`GOOGLE_API_KEY`** です。

### 主な環境変数（例）

| 用途 | 変数例 |
|------|--------|
| Gemini 要約 | `GOOGLE_API_KEY` または `GOOGLE_API_KEY_1` … `GOOGLE_API_KEY_N`、範囲 `API_KEY_RANGE` 等は `m03_api_key_manager.py` 参照 |
| 真実度の検索グラウンディング | 既定ON。`TRUTH_ASSESSMENT_GROUNDING=0` でオフ可 |
| 送信先メール | `MAIL_TO` または `TO_EMAIL` |
| Gmail 送信 | `GMAIL_USER`（Gmail 全文）、`GMAIL_APP_PASSWORD`（16 文字） |
| 要約サイト生成 | `BUILD_HTML_SITE=1` … パイプライン完了後に `docs/` を再生成（`run_pipeline_urls.sh` は全件キュー完了後に1回） |

## スクリプトの流れ（ファイル名の数字が処理順の目安）

| モジュール | 役割 |
|------------|------|
| **a01** `a01_get_transcript.py` | 字幕の取得。単体なら `python a01_get_transcript.py` |
| **a02** `a02_summary_prompt_shared.py` | 要約・真実度用のプロンプト定義（import のみ） |
| **a03** `a03_gemini_summary.py` | Gemini で要約し `summary.txt` 用テキストを生成 |
| **a04** `a04_send_result_email.py` | Gmail（SMTP）で成果物を送信 |
| **a05** `a05_pipeline_youtube_to_email.py` | 上記を 1 本で実行 |
| **build_html_site** `build_html_site.py` | `output/` の要約から `docs/` 静的サイトを生成（GitHub Pages 用） |

一括（推奨）:

```bash
python a05_pipeline_youtube_to_email.py --to your@gmail.com "https://www.youtube.com/watch?v=xxxx"
```

- 送信先を省略し `MAIL_TO` も未設定のときにメール不要なら **`--skip-email`**
- 成果物は既定で `output/<日時>_<動画ID先頭8文字>/`（`transcript.txt`, `summary.txt`, `subtitle_*.vtt`, `video_info.json` など）
- その他: `-l` 字幕言語優先（例: `ja en`）, `--prompt-mode`（`brief` / `detailed` / `minutes` / `custom`）, `--skip-truth-assessment`

### `run_pipeline.sh`（Bash: Git Bash / WSL / Cloud Shell 等）

仮想環境の作成・依存インストール・`a05` 起動までを行い、**リポジトリ直下の `.env` をシェルに展開**したうえで、`MAIL_TO` / `TO_EMAIL` の有無で `--skip-email` を切り替えます。

```bash
chmod +x run_pipeline.sh
./run_pipeline.sh "https://youtu.be/xxxx"
```

- **引数は YouTube の URL（または video_id）だけ**（`./run_pipeline.sh` と URL のあいだにスペースが必要です）。
- **Linux / Cloud Shell 等で `nohup` がある場合**: `python -u` を **`batch1.log`**（リポジトリ直下）へリダイレクトしつつバックグラウンド起動し、**シェルはすぐプロンプトに戻ります**。PID とログパスを表示します。進捗は `tail -f batch1.log` など。`nohup` により端末を閉じても Python 側は残りやすいです。
- **`nohup` が無い環境**（一部の Git Bash など）: 同様にバックグラウンド起動してすぐ戻ります（端末を閉じると停止しやすい）。
- 仮想環境に **pip が無い**場合（Debian 系の `venv` など）は、`ensurepip` または `get-pip.py` で自動的に入れます（外向き HTTP が必要な場合あり）。
- ログ **`batch1.log` は `.gitignore` 済み**です。別ファイルにしたい場合は `run_pipeline.sh` 内の `PIPELINE_LOG` を編集してください。
- Windows では **`py -3`** を優先して仮想環境を作ります。Python が Store のスタブだけの場合は [python.org](https://www.python.org/downloads/) 版のインストールを推奨します。
- 仮想環境の Python は **`.venv/Scripts/python.exe`（Windows）または `.venv/bin/python`（Unix）を直接指定**しており、`activate` は不要です。
- **`BUILD_HTML_SITE=1`**（`.env` 可）… 1 本の処理完了後に `docs/` を再生成。詳細は **`build_html_site.py` と GitHub Pages** を参照。

### `run_pipeline_urls.sh`（URL リストを順に `run_pipeline.sh`）

`urls.txt`（または引数で渡したファイル）に **1 行 1 URL** で書き、上から順に `run_pipeline.sh` を起動します。

```bash
chmod +x run_pipeline_urls.sh
# リポジトリ直下の urls.txt を使う
./run_pipeline_urls.sh
# 別パスのリストを使う
./run_pipeline_urls.sh ../urls.txt
```

`urls.txt` の例:

```text
https://youtu.be/GwDf2lIp7sY?si=Xk-W927GI5JDgWmW
https://www.youtube.com/watch?v=DhySWbjgvIQ
```

- **間隔**: 環境変数 **`URLS_PIPELINE_GAP_SEC`**（秒、既定 **65**）。直前の `run_pipeline` 起動から指定秒以上空けてから次を起動します。
- 空行と **`#` で始まる行**は無視されます。
- **`BUILD_HTML_SITE=1`**（`.env` 可）… 全 URL の **キュー処理が終わったあと**、`docs/` を **1 回だけ**再生成します（各 `run_pipeline` ごとの再生成は行いません）。詳細は後述の **`build_html_site.py` と GitHub Pages** を参照。

### `build_html_site.py` と GitHub Pages（要約の Web 公開）

`output/` に溜まった要約（`summary.txt` / `video_info.json`）から、**GitHub Pages 用の静的サイト**を `docs/` に生成します。

**生成される構成**

```text
docs/
  index.html              # 要約一覧（カテゴリタグ付き）
  contents/
    <video_id>.html       # 動画ごとの要約ページ（例: AwQYphhyPZs.html）
```

- **`output/`** は `.gitignore` 済み（ローカルのみ）。**公開するのは `docs/`** をコミットして push する想定です。
- 実行のたびに **`output/` 全体を走査して `docs/` を上書き再生成**します（差分更新ではありません）。
- 同じ `video_id` のフォルダが複数ある場合は **最新の1件だけ**を採用します。
- 一覧の **カテゴリタグ**（投資・不動産・年金・税制・AI など）は **`categories.yaml`** のキーワードで自動判定します（最大2個）。カテゴリの追加・キーワード調整はこのファイルを編集してください。

#### 単体で `docs/` を生成する

仮想環境を有効にしたうえで、リポジトリ直下で:

```bash
python build_html_site.py
```

| オプション | 既定 | 説明 |
|------------|------|------|
| `--output-root` | `output` | 要約フォルダの親ディレクトリ |
| `--html-dir` | `docs` | HTML の出力先 |
| `--archive-dir DIR` | なし（複数可） | 追加で含める成果物フォルダ |

`run_pipeline.sh` 経由でも同じ処理が走ります（`.venv` の作成・`pip install` 込み）:

```bash
./run_pipeline.sh --finish-urls-batch-html
```

（内部で `build_html_site.py` を実行。`BUILD_HTML_SITE=1` が無いとスキップします。）

#### パイプラインと連携する（自動生成）

`.env` に次を書くと、要約完了後に `docs/` を更新できます。

```env
BUILD_HTML_SITE=1
```

| 実行方法 | `docs/` を更新するタイミング |
|----------|------------------------------|
| `./run_pipeline.sh 'https://youtu.be/…'` | **その1本**の処理完了後 |
| `./run_pipeline_urls.sh urls_mylist.txt` | **リスト全件のキュー完了後に1回** |

手動で Python を叩かなくても、上記のタイミングで `build_html_site.py` 相当が動きます。

#### GitHub Pages で公開する（初回セットアップ）

1. **要約を生成** … いつも通り `run_pipeline.sh` などで `output/` に要約を作る。
2. **`docs/` を生成** … `python build_html_site.py`、または `BUILD_HTML_SITE=1` でパイプライン実行。
3. **Git に push** … `docs/` と `categories.yaml` などをコミットして `main` に push。

```bash
git add docs/ categories.yaml
git commit -m "Update summary site"
git push origin main
```

4. **GitHub で Pages を有効化** … リポジトリの **Settings → Pages** で:
   - **Source**: Deploy from a branch
   - **Branch**: `main`
   - **Folder**: **`/docs`**

5. **公開 URL**（リポジトリ名が `py_youtube-transcript-api` の例）:

```text
https://sinzy0925.github.io/py_youtube-transcript-api/
```

数分以内に反映されます。以降は要約を更新するたびに **`build_html_site.py`（または `BUILD_HTML_SITE=1`）→ `git add docs/` → push** でサイトを更新できます。

**注意**

- リポジトリが **Public** の場合、要約テキストが誰でも閲覧できます。`.env` や `output/` は gitignore 済みですが、**公開したくない要約は `docs/` に含めない**でください。
- `docs/contents/` に古い HTML が残ることがあります（`output/` に無い `video_id` のファイルは自動削除しません）。気になる場合は `docs/contents/` を一度整理してから再生成してください。

### `run_channel.sh`（チャンネル単位で videoid 取得 → 各動画へ `run_pipeline.sh`）

**yt-dlp** でチャンネルの動画 ID を `videoids.txt` に書き、その ID ごとに **`run_pipeline.sh`** を順に起動します（`requirements.txt` に `yt-dlp` あり）。

**メインの使い方（例）:**

```bash
chmod +x run_channel.sh
./run_channel.sh --fromto 0:2 --url https://www.youtube.com/@ANNnewsCH
```

- **`--fromto 0:2`** … チャンネル「動画」一覧の**先頭を 0** とした添字の範囲（**両端含む**。この例では 3 本）。**通常は新しい動画が上**なので、0 は最新側に近い。
- **`--url`** … チャンネル URL（`https://www.youtube.com/@…` など）。代わりに **位置引数で URL を先に書く**書き方も可（例: `./run_channel.sh 'https://…' --fromto 0:2`）。

**既定の挙動**

- **パイプライン連続**（各 videoid で `run_pipeline.sh` を実行）と **`nohup` でバックグラウンド起動**がオン（従来の `--gopipeline --nohup` と同等）。Cloud Shell でセッションを閉じても外側の処理は継続しやすい構成です。
- **外側プロセスが起動した直後**に、リポジトリ直下の **`*.log` を削除**します（`batch*.log` / `channel.log` など）。**`nohup` で起動した内側**では、ログファイルを開いたまま消さないよう **`rm` はしません**。
- **`nohup` が無い環境**では警告のうえフォアグラウンドで続行します。

**よく使うオプション**

- **`--no-gopipeline`** … `videoids.txt` まで（**b01 のみ**）。パイプラインは回さない。
- **`--foreground`**（または **`--no-nohup`**）… **フォアグラウンド**で実行（`nohup` しない）。

**環境変数の例**

| 変数 | 意味 |
|------|------|
| `CHANNEL_PIPELINE_GAP_SEC` | 連続で `run_pipeline.sh` を叩く際の**最短間隔（秒）**。既定 **61**（429 回避のための間引き）。 |
| `CHANNEL_LOG` | `nohup` 時の**統合ログ**のパス。未設定時はリポジトリ直下の **`channel.log`**。 |
| `CHANNEL_OUTPUT_SLUG` | 成果物・ログのファイル名に使うスラッグ。**未設定時はチャンネル URL から推定**（例: `@foo` → `foo`）。 |

**その他**

- 親ディレクトリへシンボリックリンクを張る **`junbi.sh`** に **`run_channel.sh` も含まれます**（`run_pipeline.sh` と同様）。
- **`run_pipeline.sh` 本体は変更しません。** チャンネル連続時は `PIPELINE_LOG` で `batch_channel_<チャンネルスラッグ>_<チャンネル内インデックス>.log` に分け、`PIPELINE_OUTPUT_DIR` で成果物を `output/<スラッグ>_<インデックス>/` に出すように起動します（スラッグは URL から推定。`CHANNEL_OUTPUT_SLUG` で上書き可）。

## 使用ライブラリ

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)（字幕。API キー不要）
- `google-genai`（Gemini）
- `requests`（oEmbed 等）
- `python-dotenv`（`.env`）
- `yt-dlp`（`run_channel.sh` / `b01_channel_to_videoid.py` でチャンネルから videoid を列挙する際）
- `PyYAML`（`build_html_site.py` が `categories.yaml` を読む際）

## 注意

- 要約・真実度の「数」は**モデルが返す目安**であり、専門的なファクトチェックの代替ではありません。
- **`.env` や API キーをリポジトリに含めない**でください。誤ってコミットした場合はキーの**無効化・再発行**を行ってください。

## ライセンス

このリポジトリのオリジナル部分は [MIT License](LICENSE) です。依存パッケージ（[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) 等）は各パッケージのライセンスに従います。

著作権表示の名前は必要に応じて `LICENSE` を編集してください。
