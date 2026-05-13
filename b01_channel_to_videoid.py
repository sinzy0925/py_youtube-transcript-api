#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b01 — チャンネル URL から動画 ID を取得し、スクリプトと同じフォルダの videoids.txt に上書き保存する。

前提（あいまいさの解決）:
  - --fromto の A:B は、チャンネル「動画」タブ相当のプレイリストにおける **先頭（画面上部）を 0 とした 0-based の添字範囲（両端含む）**。
  - 多くのチャンネルでは YouTube の並びが **新しい動画が上**のため、**小さい添字ほど新しい動画**になる（例: 0 が最新付近）。
  - yt-dlp の extract_flat ではエントリに playlist_index が付かないことが多く、その場合は **返却順＝上記の並び**をそのまま使う（下の sort は同一キーでは順序不変）。
  - videoids.txt の出力先はこの .py と同じディレクトリ。

依存: yt-dlp（requirements.txt に記載）

例:
    python b01_channel_to_videoid.py https://www.youtube.com/@ANNnewsCH --fromto 0:2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except OSError:
        pass


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


def main() -> int:
    p = argparse.ArgumentParser(
        description="YouTube チャンネル URL から videoid を取得し videoids.txt に書き込む",
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
        ids = fetch_video_ids_playlist(url, start, end)
    except Exception as e:
        print(f"取得に失敗しました: {e}", file=sys.stderr)
        return 1

    expected = end - start + 1
    if len(ids) < expected:
        print(
            f"警告: 要求 {expected} 件に対し {len(ids)} 件しか取得できませんでした（チャンネルが短いか、取得制限の可能性）",
            file=sys.stderr,
        )

    if not ids:
        print("動画 ID が1件も取得できませんでした。", file=sys.stderr)
        return 1

    text = "\n".join(ids) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(f"{len(ids)} 件を {out_path} に書き込みました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
