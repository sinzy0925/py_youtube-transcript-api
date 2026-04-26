# py-youtube-transcript-api

YouTube 動画の**字幕取得**（[jdepoix/youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)）→ **Gemini による要約**（真実度の目安の付与可）→ **Gmail 送信**までを一括で行うスクリプト群です。API キーは複数本ローテーションする `m03_api_key_manager` に対応します。

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

## 使用ライブラリ

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)（字幕。API キー不要）
- `google-genai`（Gemini）
- `requests`（oEmbed 等）
- `python-dotenv`（`.env`）

## 注意

- 要約・真実度の「数」は**モデルが返す目安**であり、専門的なファクトチェックの代替ではありません。
- **`.env` や API キーをリポジトリに含めない**でください。誤ってコミットした場合はキーの**無効化・再発行**を行ってください。

## ライセンス

このリポジトリのオリジナル部分は [MIT License](LICENSE) です。依存パッケージ（[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) 等）は各パッケージのライセンスに従います。

著作権表示の名前は必要に応じて `LICENSE` を編集してください。
