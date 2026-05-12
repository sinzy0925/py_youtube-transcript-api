"""
a01 — ステップ1: YouTube 字幕の取得（CLI 可）
    次: パイプラインでは a03 要約 → a04 メール。a02 はプロンプト定義（import のみ）。
https://github.com/jdepoix/youtube-transcript-api
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except OSError:
        pass

from youtube_transcript_api import (
    FetchedTranscript,
    FetchedTranscriptSnippet,
    YouTubeTranscriptApi,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.formatters import JSONFormatter, TextFormatter, WebVTTFormatter


def is_youtube_transcript_ip_block_error(exc: BaseException) -> bool:
    """youtube-transcript-api の IP / データセンター遮断系（CouldNotRetrieveTranscript の文言含む）。"""
    if isinstance(exc, (RequestBlocked, IpBlocked)):
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    if "youtube is blocking requests from your ip" in msg:
        return True
    if "could not retrieve a transcript" in msg and "cloud provider" in msg:
        return True
    if "could not retrieve a transcript" in msg and "blocking requests from your ip" in msg:
        return True
    return False


def _youtube_data_api_fallback_keys() -> list[str]:
    """
    字幕フォールバック専用: .env の youtube-api-key。
    1 行にカンマ区切りで複数キーを並べればローテーション対象に順に追加される。
    """
    out: list[str] = []
    raw = (os.getenv("youtube-api-key") or "").strip().strip('"').strip("'")
    if not raw:
        return out
    for part in re.split(r"\s*,\s*", raw):
        v = part.strip().strip('"').strip("'")
        if v and v not in out:
            out.append(v)
    return out


def _vtt_timestamp_to_seconds(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


_VTT_TIME_LINE = re.compile(
    r"^(?P<s>\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<e>\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
)


def _strip_vtt_inline_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def parse_webvtt_to_fetched(
    video_id: str,
    vtt_text: str,
    language_code: str,
    *,
    language_label: str,
    is_generated: bool,
) -> FetchedTranscript:
    """WEBVTT 文字列から FetchedTranscript を組み立てる（yt-dlp 等の出力用）。"""
    body = re.split(r"\n\n+", vtt_text.strip(), maxsplit=1)
    raw = body[-1] if len(body) > 1 else vtt_text
    chunks = re.split(r"\n\n+", raw.strip())
    snippets: list[FetchedTranscriptSnippet] = []
    for ch in chunks:
        lines = [ln.rstrip() for ln in ch.splitlines() if ln.strip()]
        if not lines:
            continue
        m = _VTT_TIME_LINE.match(lines[0])
        if not m:
            continue
        start = _vtt_timestamp_to_seconds(m.group("s"))
        end = _vtt_timestamp_to_seconds(m.group("e"))
        duration = max(0.05, end - start)
        text = _strip_vtt_inline_tags("\n".join(lines[1:]))
        if not text:
            continue
        snippets.append(FetchedTranscriptSnippet(text=text, start=start, duration=duration))
    if not snippets:
        raise ValueError("WEBVTT から字幕行を解釈できませんでした。")
    return FetchedTranscript(
        snippets=snippets,
        video_id=video_id,
        language=language_label,
        language_code=language_code,
        is_generated=is_generated,
    )


def _try_youtube_data_api_captions(
    video_id: str,
    languages: list[str],
) -> FetchedTranscript | None:
    """
    YouTube Data API v3 captions を .env の youtube-api-key（複数時は順に）で試す。
    公式 API は「API キーのみ」では第三者動画の字幕 DL ができないことが多く、
    多くの場合は 403（要 OAuth）で失敗する。
    """
    keys = _youtube_data_api_fallback_keys()
    if not keys:
        print(
            "[a01] フォールバック用の youtube-api-key が .env にありません。",
            file=sys.stderr,
        )
        return None
    nk = len(keys)
    list_url = "https://www.googleapis.com/youtube/v3/captions"
    for ki, key in enumerate(keys):
        try:
            lr = requests.get(
                list_url,
                params={"part": "snippet", "videoId": video_id, "key": key},
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"[a01] captions.list 通信エラー (キー {ki + 1}/{nk}): {e}", file=sys.stderr)
            continue
        if lr.status_code != 200:
            print(
                f"[a01] captions.list HTTP {lr.status_code} (キー {ki + 1}/{nk}): "
                f"{lr.text[:200]!r}",
                file=sys.stderr,
            )
            continue
        data = lr.json()
        items = data.get("items") or []
        if not items:
            print(f"[a01] captions.list: トラックなし (キー {ki + 1}/{nk})", file=sys.stderr)
            continue

        def rank_item(it: dict) -> tuple[int, int]:
            sn = it.get("snippet") or {}
            lang = (sn.get("language") or "").lower()
            pref = languages.index(lang) if lang in languages else len(languages) + 5
            asr = 1 if sn.get("trackKind") == "ASR" else 0
            return (pref, asr)

        items_sorted = sorted(items, key=rank_item)
        for it in items_sorted:
            cid = it.get("id")
            if not cid:
                continue
            sn = it.get("snippet") or {}
            lang_code = (sn.get("language") or "und").lower()
            is_asr = sn.get("trackKind") == "ASR"
            try:
                dr = requests.get(
                    f"https://www.googleapis.com/youtube/v3/captions/{cid}",
                    params={"tfmt": "vtt", "key": key},
                    timeout=30,
                )
            except requests.RequestException as e:
                print(f"[a01] captions.download 通信エラー: {e}", file=sys.stderr)
                continue
            if dr.status_code != 200:
                print(
                    f"[a01] captions.download HTTP {dr.status_code}: {dr.text[:200]!r}",
                    file=sys.stderr,
                )
                continue
            vtt = dr.content.decode("utf-8", errors="replace")
            try:
                return parse_webvtt_to_fetched(
                    video_id,
                    vtt,
                    lang_code,
                    language_label=lang_code,
                    is_generated=is_asr,
                )
            except ValueError as e:
                print(f"[a01] VTT パース失敗: {e}", file=sys.stderr)
                continue
    return None


def _try_ytdlp_subtitles(
    video_id: str,
    languages: list[str],
    workdir: str,
) -> FetchedTranscript | None:
    """youtube-transcript-api がブロックされたときの別経路（同一 IP でも通ることがある）。"""
    try:
        import yt_dlp
    except ImportError:
        print("[a01] yt-dlp が import できません（requirements に含めてください）。", file=sys.stderr)
        return None

    os.makedirs(workdir, exist_ok=True)
    base = os.path.join(workdir, "ytdlfallback")
    for old in glob.glob(os.path.join(workdir, "ytdlfallback*")):
        try:
            os.remove(old)
        except OSError:
            pass
    watch = video_watch_url(video_id)
    ydl_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": languages,
        "outtmpl": base + ".%(ext)s",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([watch])
    except Exception as e:
        print(f"[a01] yt-dlp 字幕取得に失敗: {e}", file=sys.stderr)
        return None

    paths = sorted(Path(workdir).glob("ytdlfallback*.vtt"))
    if not paths:
        print("[a01] yt-dlp が VTT を出力しませんでした。", file=sys.stderr)
        return None

    def lang_of(p: Path) -> str:
        stem = p.stem
        if "." in stem:
            return stem.rsplit(".", 1)[-1].lower()
        return ""

    ranked = sorted(
        paths,
        key=lambda p: (
            languages.index(lang_of(p)) if lang_of(p) in languages else len(languages) + 9,
            str(p),
        ),
    )
    chosen = ranked[0]
    lang_code = lang_of(chosen) or (languages[0] if languages else "und")
    try:
        vtt_text = chosen.read_text(encoding="utf-8", errors="replace")
        return parse_webvtt_to_fetched(
            video_id,
            vtt_text,
            lang_code,
            language_label=lang_code,
            is_generated=True,
        )
    except ValueError as e:
        print(f"[a01] yt-dlp VTT の解釈に失敗: {e}", file=sys.stderr)
        return None


def _fetch_transcript_with_fallbacks(
    video_id: str,
    languages: list[str],
    ytdlp_workdir: str,
) -> FetchedTranscript:
    ytt = YouTubeTranscriptApi()
    try:
        return ytt.fetch(video_id, languages=languages)
    except Exception as primary:
        if not is_youtube_transcript_ip_block_error(primary):
            raise
        print(
            "[a01] youtube-transcript-api が IP ブロック等で失敗しました。"
            " YouTube Data API（.env の youtube-api-key）で再試行します。",
            file=sys.stderr,
            flush=True,
        )
        got = _try_youtube_data_api_captions(video_id, languages)
        if got is not None:
            return got
        print(
            "[a01] YouTube Data API では取得できませんでした。"
            " yt-dlp で字幕取得を試します。",
            file=sys.stderr,
            flush=True,
        )
        got = _try_ytdlp_subtitles(video_id, languages, ytdlp_workdir)
        if got is not None:
            return got
        raise primary


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
    fetched = _fetch_transcript_with_fallbacks(video_id, languages, archive_dir)
    txt = TextFormatter().format_transcript(fetched)
    vtt = WebVTTFormatter().format_transcript(fetched)
    safe = re.sub(r"[^\w-]+", "_", fetched.language_code).strip("_") or "und"
    vtt_name = f"subtitle_{safe}.vtt"
    with open(os.path.join(archive_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(archive_dir, vtt_name), "w", encoding="utf-8") as f:
        f.write(vtt)
    for p in glob.glob(os.path.join(archive_dir, "ytdlfallback*")):
        try:
            os.remove(p)
        except OSError:
            pass
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

    if list_only:
        ytt = YouTubeTranscriptApi()
        try:
            tr_list = ytt.list(video_id)
        except VideoUnavailable as e:
            print(f"動画が利用できません: {e}", file=sys.stderr)
            return 3
        except (RequestBlocked, IpBlocked) as e:
            print(
                f"YouTube から IP がブロックされています: {e}\n"
                "README のプロキシ設定を参照してください。",
                file=sys.stderr,
            )
            return 6
        except Exception as e:
            if is_youtube_transcript_ip_block_error(e):
                print(
                    f"YouTube から IP がブロックされています: {e}\n"
                    "README のプロキシ設定を参照してください。",
                    file=sys.stderr,
                )
                return 6
            raise
        print(f"video_id: {video_id}\n")
        for t in tr_list:
            gen = "自動生成" if t.is_generated else "手動"
            trans = "翻訳可" if t.is_translatable else "翻訳不可"
            print(f"  [{t.language_code}] {t.language} ({gen}, {trans})")
        return 0

    try:
        with tempfile.TemporaryDirectory() as tmp:
            fetched = _fetch_transcript_with_fallbacks(video_id, languages, tmp)
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
    except VideoUnavailable as e:
        print(f"動画が利用できません: {e}", file=sys.stderr)
        return 3
    except (RequestBlocked, IpBlocked) as e:
        print(
            f"YouTube から IP がブロックされています: {e}\n"
            "README のプロキシ設定を参照してください。",
            file=sys.stderr,
        )
        return 6
    except Exception as e:
        if is_youtube_transcript_ip_block_error(e):
            print(
                f"YouTube から IP がブロックされています（フォールバック後も失敗）: {e}\n"
                "README のプロキシ設定を参照してください。",
                file=sys.stderr,
            )
            return 6
        raise

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
