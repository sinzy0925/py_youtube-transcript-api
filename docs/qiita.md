# 【備忘＆紹介】YouTube 字幕取得 → Gemini 要約 → Gmail 一括、Python パイプライン（MIT）

> この記事は **Qiita 投稿用** に書いた下書きです。手元のリポジトリと同期しています。  
> 宣伝: 同内容のオープンソースは **[GitHub: py_youtube-transcript-api](https://github.com/sinzy0925/py_youtube-transcript-api)**（**MIT**）で公開しています。使えそうならスターや issue 歓迎です。

## 要約

**ブラウザ拡張なし・Selenium なし**で、

1. 指定 YouTube 動画の**字幕**を取得（[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)）  
2. **Gemini** で長文要約＋**真実度（目安）%** 付与（JSON／検索グラウンディング可）  
3. 任意で **Gmail** に `transcript` / `summary` / 字幕 vtt などを添付送信  

までを **1 コマンド**（または `run_pipeline.sh` 1 本）で回せる小さなスクリプト集です。  
**複数本の `GOOGLE_API_KEY_N` をローテーション**するマネージャ（`m03`）入り。

---

## こんな用途向き

- 勉強会・解説動画の**内容を要約**して残したい（メールやフォルダに）  
- **字幕だけ**抜きたい（`text` / `json` / `vtt`）  
- クラウド上（Google Cloud Shell 等）の **Bash から**回したい  
- すでに **Gemini API** や **Gmail アプリパスワード** を使っている人

---

## 特徴（ざっくり）

| 内容 | 説明 |
|------|------|
| 字幕 | 公式非公開の内部 API 相当を叩く定番 Python ラッパー利用（無料、別途 API キー不要） |
| 要約 | `google-genai` で `a02` 共通プロンプト → `a03` で生成。モード `brief` / `detailed` / `minutes` / `custom` |
| 真実度 | 要約**前**の全文に対し追加で Gemini 呼び出し。`.env` で検索付きON/OFF可。地政学解説を安易に「架空扱い」しにくいプロンプト調整入り（目安） |
| メール | `a04` で HTML 本文＋添付。Markdown の `summary` も拡張があれば HTML 化 |
| キー | `m03_api_key_manager` で `GOOGLE_API_KEY_1` 番台をセッションファイル付きでローテ |

---

## 全体の流れ

```text
URL / video_id
   → a01  字幕 + transcript.txt + subtitle_*.vtt
   → oEmbed でタイトル + video_info.json
   → a03  真実度（任意）+ 要約 → summary.txt
   → a04  （任意）Gmail
```

ファイル名の **`a01` 〜 `a05`** は実行順の目安。`a02` は**プロンプト定義の import 用**（単体起動しません）。

---

## 必要なもの

- **Python 3.10+**（3.12 / 3.13 想定）  
- **Git** からクローン可能な環境  
- **Google Gemini 用 API キー**（[AI Studio 等](https://aistudio.google.com/)）  
- **メールまでやる場合**  
  - Gmail アドレス  
  - 2 段階認証＋[アプリパスワード](https://support.google.com/accounts/answer/185833)（16 文字、通常ログインパスワードではない）  
- **ネット接続**（YouTube / Google API / oEmbed 用 `requests`）  

**注意（字幕）**  
一部データセンターや **クラウド IP** からは、YouTube 側の制限で `RequestBlocked` 等になることがあります。README の[プロキシ案内](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)を参照するか、**自宅回線**で試してください。

---

## セットアップ

```bash
git clone https://github.com/sinzy0925/py_youtube-transcript-api.git
cd py_youtube-transcript-api
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
```

**依存**（`requirements.txt`）: `youtube-transcript-api`, `requests`, `google-genai`, `python-dotenv`

---

## `.env` の置き方（推奨）

リポジトリ**直下**に `.env`（**必ず .gitignore 済み**。コミット禁止）。

### 例（値は仮。実キーに差し替え）

```env
# Gemini（m03 は GOOGLE_API_KEY_1, _2, ... 番号付き推奨）
GOOGLE_API_KEY_1=your_key_here
# GOOGLE_API_KEY_2=...
# 任意: API_KEY_RANGE=1-3  など

# パイプラインの送り先（a05 / run_pipeline.sh 判定用）
MAIL_TO=your.email@gmail.com

# Gmail 送信
GMAIL_USER=your.gmail.sender@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # スペースなし16文字推奨

# 真実度で Google 検索グラウンディング（既定: 利用）
# TRUTH_ASSESSMENT_GROUNDING=0
```

- `m03_api_key_manager` は同じ `.env` を読み、番号付きキーを**範囲指定**で切り出せます（詳細は `m03_api_key_manager.py` 内コメント）。  
- **プッシュ前に** `.env` がステージに乗っていないか `git status` で確認。GitHub の **secret scan** に引っかかると拒否されるので、**キーはリポジトリに入れない**。

---

## 使い方（詳細）

### 1. 一括パイプライン（いちばん手軽）

**メール付き**（`--to` か環境変数 `MAIL_TO` / `TO_EMAIL`）:

```bash
python a05_pipeline_youtube_to_email.py --to 宛先@example.com "https://www.youtube.com/watch?v=動画ID"
```

**要約・字幕までは出して、メールは不要**:

```bash
python a05_pipeline_youtube_to_email.py --skip-email "https://youtu.be/xxxx"
```

**成果物のフォルダ**（省略時は `output/日時_動画ID先頭8文字/`）:

```bash
python a05_pipeline_youtube_to_email.py --skip-email -o ./my_out "https://www.youtube.com/watch?v=xxxx"
```

#### `a05` 主なオプション

| オプション | 内容 |
|------------|------|
| `video` | 第 1 引数。`watch` URL / `youtu.be` / 11 文字の video_id |
| `-o`, `--output-dir` | 出力ディレクトリ。未指定は `output/…` 自動 |
| `--to` | 送信先メール（使う場合。未使用なら `MAIL_TO` 等） |
| `-l`, `--languages` | 字幕の優先言語。例: `-l ja en`（デフォルト `ja en`） |
| `--prompt-mode` | `brief` / `detailed` / `minutes` / `custom`（デフォルト `detailed`） |
| `--prompt-text` | `custom` のときの本文用追記 |
| `--skip-email` | メールを送らない |
| `--skip-truth-assessment` | 真実度用の**追加** Gemini 呼び出しを行わない（要約だけ） |

**※** `MAIL_TO` も `TO_EMAIL` も空で、かつ `--skip-email` も付けていないと、**送信先未指定**で exit 2 になります。

---

### 2. 字幕だけ取りたい（CLI）

```bash
# 例: 利用可能な字幕一覧
python a01_get_transcript.py "URL" --list

# プレーンテキスト
python a01_get_transcript.py "URL" -f text

# JSON / vtt
python a01_get_transcript.py "URL" -f json
python a01_get_transcript.py "URL" -f vtt
```

- 第 1 引数を省略すると、リポ内の**サンプル用デフォルト URL**（開発者向け）にフォールスします。本番利用では**必ず URL か ID** を付けてください。  
- PowerShell では `?` 付き URL は **必ずクォート**（`"https://...?si=..."`）。

---

### 3. Bash ワンショット `run_pipeline.sh`（仮想環境まで）

**Git Bash** / WSL / **Google Cloud Shell** 等で:

```bash
chmod +x run_pipeline.sh
./run_pipeline.sh "https://youtu.be/xxxx?si=...."
```

- 同ディレクトリの **`.env` をシェルに展開**してから `a05` を起動するので、**`MAIL_TO` が `.env` だけ**でも **メール送信**ルートに入れます。  
- `.env` に `MAIL_TO` も `TO_EMAIL` も**無い**場合は、自動で **`--skip-email`**。  
- Windows では **`py -3`** を優先（Store の空の `python3` スタブで venv が壊れないよう対策）。  
- 仮想環境は **`.venv/Scripts/python.exe`（Win）or `.venv/bin/python`** を直接呼び、**`activate` に依存しない**実装。

---

## 成果物（イメージ）

`output/2026xxxx_xxxxxxxx/` 配下の例:

| ファイル | 内容 |
|----------|------|
| `transcript.txt` | プレーンテキストの全文 |
| `subtitle_ja.vtt` 等 | WebVTT 形式の字幕 |
| `summary.txt` | 真実度ブロック＋要約（先頭に「約◯%」風、設定による） |
| `video_info.json` | タイトル・video_id・取得日時 等 |

---

## うまくいかないとき

| 現象 | 想定原因と対策 |
|------|----------------|
| 字幕取得で IP ブロック | 別ネット / ドキュメントの[プロキシ](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception) |
| Gemini 429 | クォート超過。`m03` の別キーに切替・時間を空ける。`a03` にキー再試行ロジックあり |
| 真実度の「検索+JSON」が 400 | 一部モデルはツールと `application/json` 併用不可。`a03` 側で **JSON 単独**等へフォールバック |
| push が拒否される | 履歴に `.env` 混入。キー**ローテ** + `git filter-repo` 等で履歴掃除、または GitHub 案内の解除フロー（**根本はキー再発行**） |
| `run_pipeline.sh` がすぐ落ちる | Windows では [python.org](https://www.python.org/downloads/) 版の Python 推奨。`python3` だけの Store スタブに注意 |

---

## 真実度・要約の注意

- **要約**も**真実度の数値**も、**大規模言語モデルが返す推定**です。**裁判・医療・投資**などの根拠には使わないでください。  
- 地政学や時事解説を、**誤って「小説的架空」扱い**しにくいようプロンプトは調整済みですが、**誤答は起こり得ます**。

---

## ライセンス

リポジトリ内の**オリジナル**は [MIT](https://github.com/sinzy0925/py_youtube-transcript-api/blob/main/LICENSE) です。  
[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) 等の依存は、**各作者のライセンス**に従います。

---

## おわりに

「動画を見る時間はないが、内容とファイルだけ手元に残したい」という用途向けの**自分用ツール**から切り出したものです。同じ悩みの方の参考になれば幸いです。

- **リポジトリ:** https://github.com/sinzy0925/py_youtube-transcript-api  
- **Issue / PR** も歓迎（仕様の相談可）

---

（Qiita 投稿時は、タグ例: `Python` `YouTube` `Gemini` `Gmail` `youtube-transcript-api` などを付与すると捗ります。表やコードブロックはこのまま貼れます。タイトルは記事化時に 60 文字前後に整えるとよいです。）
