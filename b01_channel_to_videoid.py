#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b01 — チャンネル URL から動画 ID と公開日を取得し、videoids.txt に上書き保存する。

前提（あいまいさの解決）:
  - --fromto の A:B は、チャンネル「動画」タブ相当のプレイリストにおける **先頭（画面上部）を 0 とした 0-based の添字範囲（両端含む）**。
  - 多くのチャンネルでは YouTube の並びが **新しい動画が上**のため、**小さい添字ほど新しい動画**になる（例: 0 が最新付近）。
  - yt-dlp の extract_flat ではエントリに playlist_index / upload_date が付かないことが多い。
    ID 列挙は flat、公開日は各動画を個別に取得する。
  - videoids.txt の各行: `<videoid>\\t<YYYYMMDD>`（公開日。取得不可時は空欄）。
  - videoids.txt の出力先はこの .py と同じディレクトリ。

依存: yt-dlp（requirements.txt に記載）

例:
    python b01_channel_to_videoid.py https://www.youtube.com/@ANNnewsCH --fromto 0:2
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except OSError:
        pass

_UPLOAD_DATE_RE = re.compile(r"^\d{8}$")


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def parse_fromto(spec: str) -> tuple[int, int]:
    spec = spec.strip()
    if ":" not in spec:
        raise ValueError("--fromto は start:end 形式で指定してください（例: 0:2）")
    left, _, right = spec.partition(":")
    start_s, end_s = left.strip(), right.strip()
    if not start_s or not end_s:
        raise ValueError("--fromto は start:end 形式で指定してください（例: 0:2）")
    try:
        start = int(start_s)
        end = int(end_s)
    except ValueError as e:
        raise ValueError("--fromto の start/end は整数にしてください") from e
    if start < 0 or end < 0:
        raise ValueError("--fromto の start/end は 0 以上にしてください")
    if start > end:
        raise ValueError("--fromto では start が end 以下である必要があります")
    return start, end


def normalize_channel_videos_url(url: str) -> str:
    """チャンネルの「動画」タブ相当の URL にそろえる。"""
    u = url.strip().rstrip("/")
    low = u.lower()
    if "youtube.com" not in low and "youtube-nocookie.com" not in low:
        raise ValueError("YouTube のチャンネル URL を指定してください")
    if "/playlist?" in low:
        return url.strip()
    if low.endswith("/videos"):
        return u
    return u + "/videos"


def _normalize_upload_date(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if _UPLOAD_DATE_RE.fullmatch(s):
        return s
    return ""


def fetch_upload_date(video_id: str) -> str:
    """単一動画の公開日 YYYYMMDD を返す（不可時は空文字）。"""
    import yt_dlp

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return _normalize_upload_date(info.get("upload_date"))


def fetch_video_ids_playlist(url: str, start: int, end: int) -> list[str]:
    """yt-dlp の playlist_items（1-based）で start+1 .. end+1 を取り、extract_flat 時の返却順で ID を返す。"""
    import yt_dlp

    one_lo = start + 1
    one_hi = end + 1
    playlist_items = f"{one_lo}-{one_hi}" if one_lo != one_hi else str(one_lo)

    opts: dict = {
        "extract_flat": "in_playlist",
        "playlist_reverse": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "playlist_items": playlist_items,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    # extract_flat では playlist_index が None のことが多い → 同一キーで順序は維持され、yt-dlp の返却順がそのまま使われる
    entries.sort(key=lambda e: int(e.get("playlist_index") or 0))
    return [str(e["id"]) for e in entries]


def fetch_videos_with_upload_dates(url: str, start: int, end: int) -> list[tuple[str, str]]:
    """(videoid, YYYYMMDD or '') のリスト。"""
    ids = fetch_video_ids_playlist(url, start, end)
    out: list[tuple[str, str]] = []
    for i, vid in enumerate(ids, start=1):
        try:
            date = fetch_upload_date(vid)
        except Exception as e:
            print(f"警告: 公開日取得失敗 {vid}: {e}", file=sys.stderr)
            date = ""
        if not date:
            print(f"警告: 公開日なし {vid}（videoids.txt では日付欄を空にします）", file=sys.stderr)
        else:
            print(f"公開日: [{i}/{len(ids)}] {vid} → {date}")
        out.append((vid, date))
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="YouTube チャンネル URL から videoid と公開日を取得し videoids.txt に書き込む",
    )
    p.add_argument(
        "channel_url",
        help="例: https://www.youtube.com/@ANNnewsCH",
    )
    p.add_argument(
        "--fromto",
        required=True,
        metavar="START:END",
        help="チャンネル動画リストの先頭を 0 とした添字の範囲（両端含む）。通常は新しい動画が上なので 0 が最新側。例: 0:2 は 3 本",
    )
    args = p.parse_args()

    try:
        start, end = parse_fromto(args.fromto)
        url = normalize_channel_videos_url(args.channel_url)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    out_path = _script_dir() / "videoids.txt"

    try:
        rows = fetch_videos_with_upload_dates(url, start, end)
    except Exception as e:
        print(f"取得に失敗しました: {e}", file=sys.stderr)
        return 1

    expected = end - start + 1
    if len(rows) < expected:
        print(
            f"警告: 要求 {expected} 件に対し {len(rows)} 件しか取得できませんでした（チャンネルが短いか、取得制限の可能性）",
            file=sys.stderr,
        )

    if not rows:
        print("動画 ID が1件も取得できませんでした。", file=sys.stderr)
        return 1

    lines = [f"{vid}\t{date}" if date else vid for vid, date in rows]
    text = "\n".join(lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"{len(rows)} 件を {out_path} に書き込みました（形式: videoid[TAB]YYYYMMDD）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
