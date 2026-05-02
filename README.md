# py-youtube-transcript-api

YouTube 動画の**字幕取得**（[jdepoix/youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)）→ **Gemini による要約**（真実度の目安の付与可）→ **Gmail 送信**までを一括で行うスクリプト群です。API キーは複数本ローテーションする `m03_api_key_manager` に対応します。

## Google Cloud Shell でのクイックスタート

[Google Cloud Shell](https://cloud.google.com/shell) のターミナルに次の 1 行を貼り付けて実行すると、リポジトリの取得と `junbi.sh`（パイプライン用シェルへの実行権限付与・ホーム直下へのシンボリックリンク作成）までのセットアップができます。

```bash
mkdir -p py_youtube-transcript-api && curl -fsSL https://github.com/sinzy0925/py_youtube-transcript-api/archive/refs/heads/main.tar.gz | tar xz --strip-components=1 -C py_youtube-transcript-api && cd py_youtube-transcript-api && chmod +x junbi.sh && bash junbi.sh
```

続けてリポジトリ直下の **`.env`** を編集すれば実行できます（なければ `.env.sample` をコピーして作成。変数の例は後述の「`.env` に最低限書くもの」を参照）。例: `./run_pipeline.sh 'https://www.youtube.com/watch?v=…'`。初回実行時に `run_pipeline.sh` が仮想環境（`.venv`）の作成と `pip install -r requirements.txt` を行います。

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

- **`GOOGLE_API_KEY`**: [Google AI Studio](https://aistudio.google.com/) 等で発行した **Gemini 用 API キー**。
- **`TRUTH_ASSESSMENT_GROUNDING`**: `1` で真実度（目安）の検索グラウンディングを利用（`0` でオフ。未設定でも既定は ON 扱い）。
- **`TO_EMAIL`**: 成果物を送る**宛先**。代わりに **`MAIL_TO`** でも可（どちらかがあれば `run_pipeline.sh` はメール送信ルート）。
- **`GMAIL_USER`**: 送信に使う **Gmail アドレス**（通常は `@gmail.com` まで含む全文）。
- **`GMAIL_APP_PASSWORD`**: そのアカウントの **[アプリパスワード](https://support.google.com/accounts/answer/185833)**（**16 文字**。2 段階認証有効時に発行。**通常のログインパスワードではない**）。

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
- **Linux / Cloud Shell 等で `nohup` がある場合**: `python -u` で **`batch1.log`**（リポジトリ直下）へ標準出力・標準エラーを書きつつ**バックグラウンド**実行し、PID を表示して終了します。シェルを閉じても処理が残りやすくなります。
- **`nohup` が無い環境**（一部の Git Bash など）: エラーにはせず、**フォアグラウンド**で実行します（端末を閉じると停止します）。
- 仮想環境に **pip が無い**場合（Debian 系の `venv` など）は、`ensurepip` または `get-pip.py` で自動的に入れます（外向き HTTP が必要な場合あり）。
- ログ **`batch1.log` は `.gitignore` 済み**です。別ファイルにしたい場合は `run_pipeline.sh` 内の `PIPELINE_LOG` を編集してください。
- Windows では **`py -3`** を優先して仮想環境を作ります。Python が Store のスタブだけの場合は [python.org](https://www.python.org/downloads/) 版のインストールを推奨します。
- 仮想環境の Python は **`.venv/Scripts/python.exe`（Windows）または `.venv/bin/python`（Unix）を直接指定**しており、`activate` は不要です。

### `run_channel.sh`（チャンネル単位で videoid 取得 → 各動画へ `run_pipeline.sh`）

**yt-dlp** でチャンネルの動画 ID を `videoids.txt` に書き、その ID ごとに **`run_pipeline.sh`** を順に起動します（`requirements.txt` に `yt-dlp` あり）。

**メインの使い方（例）:**

```bash
chmod +x run_channel.sh
./run_channel.sh --fromto 0:2 --url https://www.youtube.com/@ANNnewsCH
```

- **`--fromto 0:2`** … チャンネル上で**古い動画を 0 番**としたときのインデックス範囲（**両端含む**。この例では 3 本）。
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

**その他**

- 親ディレクトリへシンボリックリンクを張る **`junbi.sh`** に **`run_channel.sh` も含まれます**（`run_pipeline.sh` と同様）。
- **`run_pipeline.sh` 本体は変更しません**（各動画ごとのログは `PIPELINE_LOG` で `batch_channel_<videoid>.log` などに振り分けます）。

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
