"""
a01 — ステップ1: YouTube 字幕の取得（CLI 可）
    次: パイプラインでは a03 要約 → a04 メール。a02 はプロンプト定義（import のみ）。
https://github.com/jdepoix/youtube-transcript-api
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except OSError:
        pass

from youtube_transcript_api import (
    FetchedTranscript,
    YouTubeTranscriptApi,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.formatters import JSONFormatter, TextFormatter, WebVTTFormatter


def video_watch_url(video_id: str) -> str:
    """標準の watch URL（oEmbed やメール用）。"""
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_video_id(url_or_id: str) -> str:
    """YouTube URL またはそのままの動画 ID から 11 文字の video_id を取り出す。"""
    s = url_or_id.strip()
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    parsed = urlparse(s)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")
    if "youtu.be" in host and path:
        return path.split("/")[0][:11]
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        if path == "watch":
            q = parse_qs(parsed.query)
            v = (q.get("v") or [""])[0]
            if v:
                return v[:11]
        if path.startswith("embed/"):
            return path.split("/")[1][:11]
        if path.startswith("shorts/"):
            return path.split("/")[1][:11]
    raise ValueError(f"動画 ID を解釈できません: {url_or_id!r}")


def save_transcript_artifacts(
    archive_dir: str,
    video_ref: str,
    languages: list[str] | None = None,
) -> tuple[str, FetchedTranscript]:
    """
    字幕を取得し archive_dir に保存する（パイプライン用）。
    出力: transcript.txt, subtitle_<言語>.vtt
    戻り値: (video_id, 取得した字幕オブジェクト)
    """
    languages = languages or ["ja", "en"]
    video_id = extract_video_id(video_ref)
    os.makedirs(archive_dir, exist_ok=True)
    ytt = YouTubeTranscriptApi()
    fetched = ytt.fetch(video_id, languages=languages)
    txt = TextFormatter().format_transcript(fetched)
    vtt = WebVTTFormatter().format_transcript(fetched)
    safe = re.sub(r"[^\w-]+", "_", fetched.language_code).strip("_") or "und"
    vtt_name = f"subtitle_{safe}.vtt"
    with open(os.path.join(archive_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(archive_dir, vtt_name), "w", encoding="utf-8") as f:
        f.write(vtt)
    return video_id, fetched


def run(
    video_ref: str,
    languages: list[str] | None = None,
    list_only: bool = False,
    out_format: str = "text",
) -> int:
    languages = languages or ["ja", "en"]
    try:
        video_id = extract_video_id(video_ref)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    ytt = YouTubeTranscriptApi()

    if list_only:
        try:
            tr_list = ytt.list(video_id)
        except (RequestBlocked, IpBlocked) as e:
            print(
                f"YouTube から IP がブロックされています: {e}\n"
                "README のプロキシ設定を参照してください。",
                file=sys.stderr,
            )
            return 6
        except VideoUnavailable as e:
            print(f"動画が利用できません: {e}", file=sys.stderr)
            return 3
        print(f"video_id: {video_id}\n")
        for t in tr_list:
            gen = "自動生成" if t.is_generated else "手動"
            trans = "翻訳可" if t.is_translatable else "翻訳不可"
            print(f"  [{t.language_code}] {t.language} ({gen}, {trans})")
        return 0

    try:
        fetched = ytt.fetch(video_id, languages=languages)
    except TranscriptsDisabled:
        print("この動画では字幕が無効になっています。", file=sys.stderr)
        return 4
    except NoTranscriptFound:
        print(
            f"要求した言語の字幕が見つかりません: {languages}\n"
            "利用可能な言語を確認するには --list を付けて実行してください。",
            file=sys.stderr,
        )
        return 5
    except (RequestBlocked, IpBlocked) as e:
        print(
            f"YouTube から IP がブロックされています: {e}\n"
            "README のプロキシ設定を参照してください。",
            file=sys.stderr,
        )
        return 6
    except VideoUnavailable as e:
        print(f"動画が利用できません: {e}", file=sys.stderr)
        return 3

    if out_format == "json":
        out = JSONFormatter().format_transcript(fetched, indent=2, ensure_ascii=False)
    elif out_format == "vtt":
        out = WebVTTFormatter().format_transcript(fetched)
    else:
        out = TextFormatter().format_transcript(fetched)

    print(out)
    if not out.endswith("\n"):
        print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube 動画の字幕を取得します（jdepoix/youtube-transcript-api）。"
    )
    parser.add_argument(
        "video",
        nargs="?",
        default="https://www.youtube.com/watch?v=8W6Qn2hNrAM",
        help="動画 URL または 11 文字の video_id（省略時は 8W6Qn2hNrAM）",
    )
    parser.add_argument(
        "-l",
        "--languages",
        nargs="+",
        default=["ja", "en"],
        metavar="CODE",
        help="優先する言語コード（先頭から試す）。デフォルト: ja en",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="利用可能な字幕一覧のみ表示して終了",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json", "vtt"),
        default="text",
        help="出力形式: text / json / vtt",
    )
    args = parser.parse_args()
    sys.exit(
        run(
            args.video,
            languages=args.languages,
            list_only=args.list_only,
            out_format=args.format,
        )
    )


if __name__ == "__main__":
    main()
