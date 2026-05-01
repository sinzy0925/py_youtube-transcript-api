#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a05 — 一括パイプライン（これだけ実行すれば一連の処理が完了）
    内部の処理順: (1) a01 字幕取得 → (2) a02 は import のみ →
    (3) a03 要約前に真実度（目安）API1回＋要約 → (4) a04 メール

    使い方（プロジェクトルートで）:
        pip install -r requirements.txt
        python a05_pipeline_youtube_to_email.py --to you@example.com "https://www.youtube.com/watch?v=..."

    単体利用:
        a01_get_transcript.py  … 字幕のみ
        a03_gemini_summary.py  … 要約 API のみ（他から import）
        a04_send_result_email.py … メールのみ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

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

from a01_get_transcript import save_transcript_artifacts, video_watch_url
from a03_gemini_summary import SummaryToFileResult, generate_summary_to_file
from a04_send_result_email import send_result_email, write_summary_unavailable_placeholder

PYTHON = os.path.basename(__file__)
DEFAULT_VIDEO = "https://www.youtube.com/watch?v=8W6Qn2hNrAM"


def _fetch_title_via_oembed(watch_url: str) -> str:
    r = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": watch_url, "format": "json"},
        timeout=20,
    )
    r.raise_for_status()
    data: Any = r.json()
    t = (data.get("title") or "").strip()
    return t or "（タイトル不明）"


def _write_video_info(archive_dir: str, title: str, video_id: str) -> str:
    path = os.path.join(archive_dir, "video_info.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"title": title, "video_id": video_id, "fetched_utc": datetime.now(timezone.utc).isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )
    return path


def _print_pipeline_run_footer(
    summary_res: SummaryToFileResult,
    *,
    skip_email: bool,
    to_email: str,
    mail_ok: Optional[bool],
) -> None:
    """パイプライン終了直後、要約・真実度・メールの成否を1行ずつ。"""
    sm = summary_res.summary_model or "—"
    print(f"[要約]{'成功' if summary_res.ok else '失敗'} モデル：{sm}")
    if not summary_res.truth_requested:
        print(f"[真実度]スキップ モデル：—")
    elif summary_res.truth_strategy_label:
        st = "成功" if summary_res.truth_ok else "失敗"
        tm = summary_res.truth_model or "—"
        print(f"[{summary_res.truth_strategy_label}]{st}　モデル：{tm}")
    else:
        st = "成功" if summary_res.truth_ok else "失敗"
        tm = summary_res.truth_model or "—"
        print(f"[真実度]{st}　モデル：{tm}")
    if skip_email:
        print(f"[メール送信]スキップ (--skip-email) To={to_email!r}")
    else:
        ok_m = mail_ok if mail_ok is not None else False
        print(f"[メール送信]{'成功' if ok_m else '失敗'}　To={to_email!r}")


def run_pipeline(
    video_ref: str,
    archive_dir: str,
    to_email: str,
    languages: list[str],
    prompt_mode: str,
    prompt_text: str,
    skip_email: bool,
    skip_truth_assessment: bool,
) -> int:
    print(f"=== パイプライン開始 : ({PYTHON}) ===")
    os.makedirs(archive_dir, exist_ok=True)

    # --- (1) 字幕: a01 ---
    print(f"[1/3] 字幕取得 → {archive_dir}")
    try:
        video_id, _fetched = save_transcript_artifacts(archive_dir, video_ref, languages=languages)
    except Exception as e:
        print(f"字幕取得に失敗: {e} : ({PYTHON})", file=sys.stderr)
        return 1
    watch_url = video_watch_url(video_id)
    try:
        title = _fetch_title_via_oembed(watch_url)
    except Exception as e:
        print(f"警告: タイトル取得(oEmbed)に失敗、仮タイトルにします: {e} : ({PYTHON})")
        title = "（タイトル不明）"
    _write_video_info(archive_dir, title, video_id)
    tpath = os.path.join(archive_dir, "transcript.txt")
    with open(tpath, "r", encoding="utf-8") as f:
        transcript_text = f.read()
    print(f"      video_id={video_id} title={title!r}")

    # --- (2) 要約: a02+a03 ---
    summary_path = os.path.join(archive_dir, "summary.txt")
    print(f"[2/3] 要約（Gemini）→ {summary_path}")
    sum_res = generate_summary_to_file(
        transcript_text,
        summary_path,
        prompt_mode=prompt_mode,
        prompt_text=prompt_text,
        video_title=title,
        video_url=watch_url,
        include_truth_assessment=not skip_truth_assessment,
    )
    if not sum_res.ok:
        write_summary_unavailable_placeholder(
            archive_dir, video_title=title, video_url=watch_url
        )

    # --- (3) メール: a04 ---
    if skip_email:
        print(f"[3/3] メール送信をスキップ (--skip-email) : ({PYTHON})")
        print(f"=== 完了（成果物は {archive_dir}） : ({PYTHON}) ===")
        _print_pipeline_run_footer(
            sum_res,
            skip_email=True,
            to_email=to_email,
            mail_ok=None,
        )
        return 0

    print(f"[3/3] メール送信 To={to_email!r}")
    mail_ok = send_result_email(archive_dir, to_email, watch_url)
    print(f"=== 完了 : ({PYTHON}) ===")
    _print_pipeline_run_footer(
        sum_res,
        skip_email=False,
        to_email=to_email,
        mail_ok=mail_ok,
    )
    print(f"=== [終了] 成果物は {archive_dir} です。")
    print(f"=== [終了] ===")
    print(f"=== [終了] ===")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="a01 字幕 → a03 要約 → a04 メール（一括）"
    )
    p.add_argument(
        "video",
        nargs="?",
        default=DEFAULT_VIDEO,
        help="動画 URL または video_id",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        default="",
        help="成果物のディレクトリ。省略時は output/<日時>_<id短縮>/",
    )
    p.add_argument(
        "--to",
        dest="to_email",
        default="",
        help="送信先メール。省略時は環境変数 MAIL_TO / TO_EMAIL",
    )
    p.add_argument(
        "-l",
        "--languages",
        nargs="+",
        default=["ja", "en"],
        metavar="CODE",
    )
    p.add_argument(
        "--prompt-mode",
        default="detailed",
        help="a02 のモード: brief|detailed|minutes|custom",
    )
    p.add_argument(
        "--prompt-text",
        default="",
        help="prompt-mode=custom のときの追記文",
    )
    p.add_argument(
        "--skip-email",
        action="store_true",
        help="要約まですてメールを送らない",
    )
    p.add_argument(
        "--skip-truth-assessment",
        action="store_true",
        help="真実度（目安）の追加 API 呼び出しをせず、要約のみ行う",
    )
    args = p.parse_args()

    to_email = (args.to_email or os.getenv("MAIL_TO") or os.getenv("TO_EMAIL") or "").strip()
    if not args.skip_email and not to_email:
        print(
            f"送信先が未指定です。--to user@... か環境変数 MAIL_TO を設定するか、"
            f"--skip-email を付けてください。 : ({PYTHON})",
            file=sys.stderr,
        )
        sys.exit(2)

    out = args.output_dir.strip()
    if not out:
        from a01_get_transcript import extract_video_id

        try:
            vid = extract_video_id(args.video)
        except ValueError:
            vid = "unknown"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join("output", f"{ts}_{vid[:8]}")

    code = run_pipeline(
        args.video,
        out,
        to_email,
        args.languages,
        args.prompt_mode,
        args.prompt_text,
        args.skip_email,
        args.skip_truth_assessment,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
