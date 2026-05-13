# py-youtube-transcript-api

[GitHub: sinzy0925/py_youtube-transcript-api](https://github.com/sinzy0925/py_youtube-transcript-api)

YouTube の動画を指定すると、**字幕を取得し、Gemini で要約し（真実度の目安の付与可）、必要なら Gmail で結果を受け取る**までを、ターミナルからまとめて実行するスクリプト群です（ブラウザ上の GUI アプリというより **CLI 向けツールキット**）。

中身の処理は **字幕取得**（[sinzy0925/youtube-transcript-api](https://github.com/sinzy0925/youtube-transcript-api)）→ **Gemini による要約** → **Gmail 送信**です。API キーは複数本ローテーションする `m03_api_key_manager` に対応します。

### よくある使い方（3 パターン）

1. **1 本だけ** … Cloud Shell などで `.env` を用意したうえで、`./run_pipeline.sh 'https://youtu.be/…'` を実行すると、**要約などがメールで届く**（`MAIL_TO` / `TO_EMAIL` と Gmail 送信設定がある場合。無ければ `--skip-email` 相当でファイルのみ）。
2. **URL を複数** … `urls.txt` に **1 行 1 URL**（`#` 始まりと空行は無視）で書き、`./run_pipeline_urls.sh` または `./run_pipeline_urls.sh /path/to/urls.txt` で **上から順に** `run_pipeline.sh` が走り、**それぞれメールで届く**（起動間隔は `URLS_PIPELINE_GAP_SEC`、既定 65 秒）。
3. **チャンネル単位** … `./run_channel.sh --fromto 0:10 --url 'https://www.youtube.com/@…'` のように **`--fromto` で範囲**を指定すると、その範囲の動画を **順番に**要約パイプラインへ回す（`b01` はチャンネル「動画」タブ相当の **先頭を 0** とした添字で、**多くのチャンネルでは新しい動画が上のため 0 が最新側**。範囲は両端含む。例 `0:10` は 11 本）。

**Google Cloud Shell**（Google アカウントがあれば無料枠で使える）で動かす手順を下にまとめています。ローカルは **Git Bash / WSL / Linux** などの Bash が使える環境を想定しています。

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

## スクリプトの流れ（ファイル名の数字が処理順の目安）

| モジュール | 役割 |
|------------|------|
| **a01** `a01_get_transcript.py` | 字幕の取得。単体なら `python a01_get_transcript.py` |
| **a02** `a02_summary_prompt_shared.py` | 要約・真実度用のプロンプト定義（import のみ） |
| **a03** `a03_gemini_summary.py` | Gemini で要約し `summary.txt` 用テキストを生成 |
| **a04** `a04_send_result_email.py` | Gmail（SMTP）で成果物を送信 |
| **a05** `a05_pipeline_youtube_to_email.py` | 上記を 1 本で実行 |

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
- **Linux / Cloud Shell 等で `nohup` がある場合**: `python -u` を **`batch1.log`**（リポジトリ直下）へリダイレクトしつつバックグラウンド起動し、**子プロセスの終了まで `wait`** してから戻ります（`run_channel.sh` の連続起動が並列にならないため）。PID を表示します。`nohup` により端末を閉じても Python 側は残りやすいです。
- **`nohup` が無い環境**（一部の Git Bash など）: エラーにはせず、**フォアグラウンド**で実行します（端末を閉じると停止します）。
- 仮想環境に **pip が無い**場合（Debian 系の `venv` など）は、`ensurepip` または `get-pip.py` で自動的に入れます（外向き HTTP が必要な場合あり）。
- ログ **`batch1.log` は `.gitignore` 済み**です。別ファイルにしたい場合は `run_pipeline.sh` 内の `PIPELINE_LOG` を編集してください。
- Windows では **`py -3`** を優先して仮想環境を作ります。Python が Store のスタブだけの場合は [python.org](https://www.python.org/downloads/) 版のインストールを推奨します。
- 仮想環境の Python は **`.venv/Scripts/python.exe`（Windows）または `.venv/bin/python`（Unix）を直接指定**しており、`activate` は不要です。

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

## 注意

- 要約・真実度の「数」は**モデルが返す目安**であり、専門的なファクトチェックの代替ではありません。
- **`.env` や API キーをリポジトリに含めない**でください。誤ってコミットした場合はキーの**無効化・再発行**を行ってください。

## ライセンス

このリポジトリのオリジナル部分は [MIT License](LICENSE) です。依存パッケージ（[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) 等）は各パッケージのライセンスに従います。

著作権表示の名前は必要に応じて `LICENSE` を編集してください。
