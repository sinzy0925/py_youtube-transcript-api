#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参照用の transcript.txt を読み、Gemini + Google 検索グラウンディングだけで
内容の事実関係を検証する単体スクリプト（要約パイプラインは走らせない）。

  python search_google.py
  python search_google.py path/to/transcript.txt

API キー: プロジェクト直下の .env（python-dotenv）。GOOGLE_API_KEY または
GOOGLE_API_KEY_1 …。m03 がある場合はローテーションの先頭キーも利用。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from google import genai
from google.genai import types

# 長い文字起こしは API 制限・コストのため上限（必要なら環境変数で変更）
_MAX_TRANSCRIPT_CHARS = int(os.getenv("SEARCH_GOOGLE_MAX_TRANSCRIPT_CHARS", "120000"))


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _load_env() -> None:
    if load_dotenv:
        load_dotenv(_project_root() / ".env")


def _pick_api_key() -> str | None:
    try:
        from m03_api_key_manager import api_key_manager

        k = api_key_manager.get_next_key_sync()
        if k:
            return k
    except Exception:
        pass
    for name in (
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEY_1",
        "GOOGLE_API_KEY_2",
        "GOOGLE_API_KEY_3",
        "GOOGLE_API_KEY_4",
        "GOOGLE_API_KEY_5",
        "GOOGLE_API_KEY_6",
    ):
        v = (os.getenv(name) or "").strip()
        if v:
            return v
    return None


def _default_transcript_path() -> Path:
    return (
        _project_root()
        / "output"
        / "20260426_190249_2UF8PHOI"
        / "transcript.txt"
    )


def _default_model() -> str:
    try:
        from m03_gemini_model_fallback import get_gemini_model_fallback_chain

        chain = get_gemini_model_fallback_chain(for_summary=True)
        if chain:
            return chain[0]
    except ImportError:
        pass
    #return os.getenv("SEARCH_GOOGLE_MODEL", "gemini-3-flash-preview")
    #return os.getenv("SEARCH_GOOGLE_MODEL", "gemini-2.5-flash-lite")
    return os.getenv("SEARCH_GOOGLE_MODEL", "gemini-2.5-flash")


def _build_instruction() -> str:
    return """あなたはファクトチェック助手です。ユーザーが渡す「文字起こし」について、
Google 検索ツールで公開情報を参照し、次を日本語で報告してください。

1) 文字起こしに含まれる主な事実・数値・固有名詞・因果の主張を要約
2) 検索で裏付けできる点 / 出典と矛盾・不確かな点 / 断定できない点
3) 総合所感（断定は控え、検索根拠を簡潔に）

注意: 文字起こしは信頼できる一次ソースではない前提で扱ってください。
"""


def main() -> int:
    _load_env()

    p = argparse.ArgumentParser(
        description="transcript.txt を参照に Gemini + Google 検索で事実確認のみ行う"
    )
    p.add_argument(
        "transcript",
        nargs="?",
        type=Path,
        default=_default_transcript_path(),
        help="検証対象の transcript.txt（省略時は既定の output/.../transcript.txt）",
    )
    p.add_argument(
        "--model",
        default="",
        help="Gemini モデル ID（省略時はフォールバック列の先頭 or gemini-3-flash-preview）",
    )
    args = p.parse_args()
    path: Path = args.transcript
    if not path.is_file():
        print(f"エラー: ファイルがありません: {path}", file=sys.stderr)
        return 1

    api_key = _pick_api_key()
    if not api_key:
        print(
            "エラー: API キーがありません。.env に GOOGLE_API_KEY 等を設定してください。",
            file=sys.stderr,
        )
        return 1

    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        print("エラー: 文字起こしが空です。", file=sys.stderr)
        return 1
    truncated = False
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = text[:_MAX_TRANSCRIPT_CHARS]
        truncated = True

    model = (args.model or "").strip() or _default_model()
    instruction = _build_instruction()
    user_block = (
        f"--- 文字起こしファイル: {path} ---\n\n{text}\n"
        if not truncated
        else (
            f"--- 文字起こしファイル: {path}（先頭 {_MAX_TRANSCRIPT_CHARS} 文字に切り詰め） ---\n\n{text}\n"
        )
    )

    client = genai.Client(api_key=api_key)
    tool = types.Tool(google_search=types.GoogleSearch())
    cfg = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=8192,
        tools=[tool],
    )

    print(f"モデル: {model}", file=sys.stderr)
    print("Google 検索グラウンディングで検証中…", file=sys.stderr)

    try:
        response = client.models.generate_content(
            model=model,
            contents=[instruction, "\n\n", user_block],
            config=cfg,
        )
    except Exception as e:
        print(f"エラー: Gemini API: {e}", file=sys.stderr)
        return 1

    out = (getattr(response, "text", None) or "").strip()
    if not out:
        print("警告: 応答が空です。", file=sys.stderr)
        return 2

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
