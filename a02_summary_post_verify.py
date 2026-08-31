#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a02 — 要約後の照合・修正（a03 から呼び出し）
    文字起こしと要約の固有名詞・帰属先を照合し、外部知識による置換や音声認識誤記を補正する。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

PYTHON_NAME = "a02_summary_post_verify.py"

# 投資・配当文脈でよくある音声認識の誤変換（要約修正時の参考。文字起こしは別途アンカー優先）
_STT_HINTS: tuple[tuple[str, str, str], ...] = (
    ("後輩株", "高配当株", "配当・利回り・配当株投資の文脈"),
    ("後廃株", "高配当株", "配当株の文脈"),
    ("増廃", "増配", "配当増加・増配株の文脈"),
    ("後廃", "増配", "配当増加の文脈"),
    ("森林差", "新NISA", "NISA制度の文脈"),
    ("累進配当", "累配当", "配当政策の用語（累進配当ではない場合）"),
)

_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.MULTILINE)
    for p in (
        r"著者は(?:個人投資家の|投資系YouTuberの|投資くまさん|長期株式投資さん|ヘムさん|勝さん)[^\n。]{0,80}",
        r"著者は[^\n。]{0,40}(?:さん|氏)[^\n。]{0,40}",
        r"出版は[^\n。]{0,50}",
        r"発行は[^\n。]{0,50}",
        r"出版社は[^\n。]{0,50}",
        r"本日は[^\n。]{0,120}(?:書籍|本)[^\n。]{0,80}",
        r"こちらの(?:書籍|本)[^\n。]{0,100}",
        r"『[^』]{2,100}』",
        r"タイトルにある[^\n。]{0,100}",
        r"パル出版",
        r"加川",
        r"角川",
    )
)

_VERIFY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "corrected_summary": {
            "type": "string",
            "description": "修正後の要約本文（前置き・コードフェンスなし）",
        },
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary_before": {"type": "string"},
                    "summary_after": {"type": "string"},
                    "reason": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["transcript", "stt_correction", "attribution"],
                    },
                },
                "required": ["summary_before", "summary_after", "reason", "source"],
            },
        },
    },
    "required": ["corrected_summary", "changes"],
}


class _GeminiGenerateLoop(Protocol):
    def __call__(
        self,
        api_key: str,
        models: tuple[str, ...],
        parts: list,
        *,
        temperature: float,
        max_output_tokens: int,
        purpose: str,
        use_google_search_grounding: bool = False,
        response_mime_type: Optional[str] = None,
        response_json_schema: Optional[dict] = None,
        max_attempts_override: Optional[int] = None,
        retry_delay_sec_override: Optional[float] = None,
        max_key_rotations: Optional[int] = None,
        always_rotate_key: bool = False,
        verbose_request_log: bool = False,
    ) -> Any: ...


@dataclass
class PostVerifyResult:
    """照合・修正の結果。"""

    summary: str
    api_key: str
    model: Optional[str]
    ok: bool
    changes: list[dict[str, str]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


def post_verify_enabled() -> bool:
    raw = (os.getenv("SUMMARY_POST_VERIFY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _max_transcript_chars() -> int:
    try:
        return max(8000, int((os.getenv("SUMMARY_POST_VERIFY_MAX_TRANSCRIPT_CHARS") or "60000").strip()))
    except ValueError:
        return 60000


def _stt_hints_block() -> str:
    lines = ["【音声認識（STT）でよくある誤変換の目安】"]
    lines.append(
        "文字起こしに誤記があっても、要約では次を適用してよい（文脈が一致するときのみ）："
    )
    for before, after, ctx in _STT_HINTS:
        lines.append(f"  - 「{before}」→「{after}」（{ctx}）")
    lines.append(
        "ただし著者名・書名・銘柄名・出版社名は、下記アンカー（文字起こし抜粋）に"
        "書かれている表記を最優先する。アンカーに無い名前へ推測で置き換えない。"
    )
    return "\n".join(lines)


def extract_transcript_anchors(transcript: str) -> list[str]:
    """固有名詞照合用に文字起こしからアンカー文を抽出。"""
    seen: set[str] = set()
    anchors: list[str] = []
    for pat in _ANCHOR_PATTERNS:
        for m in pat.finditer(transcript):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) < 4 or s in seen:
                continue
            seen.add(s)
            anchors.append(s)
    return anchors[:80]


def _build_verify_context(transcript: str) -> str:
    """照合用に文字起こしをアンカー優先で圧縮。"""
    max_chars = _max_transcript_chars()
    if len(transcript) <= max_chars:
        return transcript

    anchors = extract_transcript_anchors(transcript)
    anchor_block = "\n".join(f"- {a}" for a in anchors)
    head = transcript[:4000]
    tail = transcript[-4000:]
    return (
        f"（文字起こしは長いため抜粋。固有名詞はアンカーと冒頭・末尾を優先参照）\n\n"
        f"【固有名詞アンカー（文字起こしから自動抽出）】\n{anchor_block}\n\n"
        f"--- 冒頭 ---\n{head}\n\n--- 末尾 ---\n{tail}"
    )


def build_post_verify_prompt(
    video_title: str,
    transcript_context: str,
    summary_body: str,
    *,
    anchors: Optional[list[str]] = None,
) -> str:
    anchor_lines = anchors if anchors is not None else extract_transcript_anchors(transcript_context)
    anchor_section = "\n".join(f"- {a}" for a in anchor_lines[:60]) or "（抽出なし）"

    return (
        "【役割】YouTube 文字起こしに基づく要約文の「固有名詞・帰属先・STT誤記」を照合し、"
        "必要な修正だけを加えた要約を返す。\n"
        "【最重要ルール】\n"
        "1) 要約に登場する著者名・書名・出版社・銘柄名・企業名は、"
        "文字起こし（または下記アンカー）に実際に出てくる表記と一致させる。"
        "要約だけに出てくる別名（例: 文字起こしが「勝さん」なのに要約が「かん氏」）は修正する。\n"
        "2) 外部知識・検索結果・一般的な正式名称で文字起こしの表記を上書きしない。\n"
        "3) 音声認識の明らかな誤変換は、文脈がはっきりするときだけ要約内を正規化してよい"
        "（例: 配当文脈の「増廃」→「増配」）。不確かなら文字起こしのまま残し reason に記載。\n"
        "4) 各書籍・トピックの帰属先を取り違えていれば修正（例: カバードコールは勝著パートの内容）。\n"
        "5) 要約の情報量・章立て・箇条書きを削らない。短くし直さない。修正は置換・追記の最小限。\n"
        "6) 文字起こしに無い新しい事実・数値を追加しない。\n"
        f"{_stt_hints_block()}\n\n"
        f"対象動画タイトル: {video_title}\n\n"
        f"【固有名詞アンカー（文字起こし抜粋）】\n{anchor_section}\n\n"
        "【出力形式】JSON のみ。corrected_summary に修正後の要約全文。"
        "changes に修正した箇所（無ければ空配列）。\n"
        "source は transcript（アンカー準拠）/ stt_correction（STT正規化）/ attribution（帰属先修正）。\n\n"
        "--- 要約文（修正対象） ---\n"
        f"{summary_body.strip()}\n\n"
        "--- 文字起こし（照合用） ---\n"
        f"{transcript_context.strip()}\n"
    )


def _parse_verify_json(raw: str) -> Optional[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("corrected_summary"), str):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict) and isinstance(data.get("corrected_summary"), str):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _rule_based_preflight(
    summary: str,
    anchors: list[str],
    *,
    transcript_text: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """
    アンカーに明確に出ている表記へ、要約内の明らかな別名を機械的に置換。
    （LLM 呼び出し前の安全網。過剰置換を避けるため限定的）
    """
    changes: list[dict[str, str]] = []
    out = summary

    # 著者「勝さん」がアンカーまたは文字起こし全体にあれば「かん氏」等を修正
    anchor_text = "\n".join(anchors)
    transcript_hint = transcript_text or ""
    if re.search(r"勝さん", anchor_text) or re.search(r"勝さん", transcript_hint):
        for wrong in ("かん氏", "かつ氏", "カツ氏", "投資系YouTuberかん氏", "投資系YouTuber かん氏"):
            if wrong in out:
                replacement = "勝さん" if wrong.endswith("氏") else wrong.replace("かん氏", "勝さん")
                if "投資系YouTuber" in wrong:
                    replacement = "投資系YouTuberの勝さん"
                new_out = out.replace(wrong, replacement)
                if new_out != out:
                    changes.append(
                        {
                            "summary_before": wrong,
                            "summary_after": replacement,
                            "reason": "文字起こしに「勝さん」の記載あり",
                            "source": "transcript",
                        }
                    )
                    out = new_out

    if re.search(r"勝さん", anchor_text) or re.search(r"勝さん", transcript_hint):
        for wrong, right in (
            ("投資系YouTuber勝", "投資系YouTuberの勝さん"),
            ("YouTuber勝", "YouTuberの勝さん"),
            ("勝著", "勝さん著"),
        ):
            if wrong in out:
                new_out = out.replace(wrong, right)
                if new_out != out:
                    changes.append(
                        {
                            "summary_before": wrong,
                            "summary_after": right,
                            "reason": "文字起こしの著者表記「勝さん」に合わせる",
                            "source": "transcript",
                        }
                    )
                    out = new_out

    # STT: 要約内の増廃→増配（配当文脈の単語のみ）
    for wrong, right, _ctx in _STT_HINTS:
        if wrong in ("後輩株", "後廃株", "森林差"):
            continue  # 文脈依存が強いので LLM に任せる
        if wrong in out and right not in out:
            new_out = out.replace(wrong, right)
            if new_out != out:
                changes.append(
                    {
                        "summary_before": wrong,
                        "summary_after": right,
                        "reason": f"STT誤変換の正規化（{_ctx}）",
                        "source": "stt_correction",
                    }
                )
                out = new_out

    return out, changes


def verify_and_correct_summary(
    api_key: str,
    models: tuple[str, ...],
    transcript_text: str,
    summary_body: str,
    *,
    video_title: str,
    gemini_generate: _GeminiGenerateLoop,
    max_output_tokens: int = 16000,
) -> PostVerifyResult:
    """
    要約を文字起こしと照合して修正。失敗時は preflight 済み本文または原文を返す。
    """
    body = (summary_body or "").strip()
    if not body:
        return PostVerifyResult(body, api_key, None, False, skip_reason="要約が空")

    anchors = extract_transcript_anchors(transcript_text)
    preflight_body, preflight_changes = _rule_based_preflight(
        body, anchors, transcript_text=transcript_text
    )
    transcript_ctx = _build_verify_context(transcript_text)
    prompt = build_post_verify_prompt(
        video_title,
        transcript_ctx,
        preflight_body,
        anchors=anchors,
    )

    print(f"要約照合: 開始（アンカー {len(anchors)} 件） : ({PYTHON_NAME})")
    gen = gemini_generate(
        api_key,
        models,
        [prompt],
        temperature=0.1,
        max_output_tokens=max_output_tokens,
        purpose="要約照合",
        response_mime_type="application/json",
        response_json_schema=_VERIFY_JSON_SCHEMA,
    )
    raw = (getattr(gen, "text", None) or "").strip()
    api_key = getattr(gen, "api_key", api_key) or api_key
    model = getattr(gen, "model", None)

    if not raw:
        print(f"警告: 要約照合 API 失敗。preflight のみ適用 : ({PYTHON_NAME})")
        return PostVerifyResult(
            preflight_body,
            api_key,
            model,
            ok=bool(preflight_changes),
            changes=preflight_changes,
        )

    parsed = _parse_verify_json(raw)
    if not parsed:
        print(f"警告: 要約照合 JSON 解釈失敗。preflight のみ適用 : ({PYTHON_NAME})")
        return PostVerifyResult(
            preflight_body,
            api_key,
            model,
            ok=bool(preflight_changes),
            changes=preflight_changes,
        )

    corrected = (parsed.get("corrected_summary") or "").strip()
    if not corrected:
        corrected = preflight_body

    llm_changes = parsed.get("changes") or []
    if not isinstance(llm_changes, list):
        llm_changes = []
    all_changes = preflight_changes + [
        c for c in llm_changes if isinstance(c, dict)
    ]

    if all_changes:
        print(f"要約照合: {len(all_changes)} 件の修正を適用 : ({PYTHON_NAME})")
        for c in all_changes[:12]:
            before = c.get("summary_before", "")
            after = c.get("summary_after", "")
            src = c.get("source", "")
            print(f"  - [{src}] {before!r} → {after!r} : ({PYTHON_NAME})")
        if len(all_changes) > 12:
            print(f"  …他 {len(all_changes) - 12} 件 : ({PYTHON_NAME})")
    else:
        print(f"要約照合: 修正なし : ({PYTHON_NAME})")

    return PostVerifyResult(
        corrected,
        api_key,
        model,
        ok=True,
        changes=all_changes,
    )
