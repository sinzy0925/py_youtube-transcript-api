#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a03 — ステップ2: 文字起こしを Gemini で要約し summary.txt へ（単体実行可）
    真実度は (1) 検索+JSON → (2) JSON のみ → (3) 検索+自由文 → (4) 自由文 の順にフォールバック（JSON はスキーマ厳制）。
    地政学解説を「架空」と誤レッテルしないよう a02 プロンプトに明示。TRUTH_ASSESSMENT_GROUNDING=0 で検索手順を省く。
    前: a01 で transcript.txt 作成。a02 のプロンプトを import。次: a04 メール。
    API キーは m03_api_key_manager（ローテーション・.session_data.json 永続化）を優先利用。
    要約のモデル列は m03_gemini_model_fallback がある場合のみそちらを使用。
    真実度は Google 検索＋API 都合により gemini-2.5 系のみの列を用いる（要約列と切り離し）。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import NamedTuple, Optional

from google import genai
from google.genai import types

from a02_summary_prompt_shared import (
    build_prompt,
    build_truth_assessment_prompt,
    build_truth_assessment_prompt_relaxed,
)

from m03_api_key_manager import api_key_manager

# 要約: 既定のモデル試行順（m03_gemini_model_fallback 未導入時、または要約専用）
_DEFAULT_SUMMARY_MODELS: tuple[str, ...] = (
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)

# 真実度（検索／JSON 等）: 3.1 / 3 プレビューで環境により失敗しやすいため 2.5 系のみ試行
_DEFAULT_TRUTH_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)

try:
    from m03_gemini_model_fallback import get_gemini_model_fallback_chain
except ImportError:
    get_gemini_model_fallback_chain = None  # type: ignore[misc, assignment]


def _summary_model_chain() -> tuple[str, ...]:
    """要約用モデル列。m03 があるときは get_gemini_model_fallback_chain(for_summary=True)、なければ既定4種。"""
    if get_gemini_model_fallback_chain is not None:
        chain = get_gemini_model_fallback_chain(for_summary=True)
        if chain:
            return chain
    return _DEFAULT_SUMMARY_MODELS


def _truth_model_chain() -> tuple[str, ...]:
    """真実度用モデル列（要約とは独立。環境変数 GEMINI_TRUTH_MODELS で上書き可・カンマ区切り）。"""
    raw = (os.getenv("GEMINI_TRUTH_MODELS") or "").strip()
    if raw:
        parts = tuple(m.strip() for m in raw.split(",") if m.strip())
        if parts:
            return parts
    return _DEFAULT_TRUTH_MODELS

PYTHON_NAME = os.path.basename(__file__)


class SummaryToFileResult(NamedTuple):
    """generate_summary_to_file の戻り値。パイプライン末尾のサマリ行用。"""

    ok: bool
    summary_model: Optional[str]
    truth_requested: bool
    truth_ok: bool
    truth_strategy_label: Optional[str]
    truth_model: Optional[str]


# 真実度 API の JSON 厳制（プロンプトと揃え、パース失敗を減らす）
_TRUTH_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "score_percent": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
        "reason": {
            "type": "string",
        },
    },
    "required": ["score_percent", "reason"],
}


def _truth_assessment_grounding_enabled() -> bool:
    """真実度 API に Google 検索グラウンディング（公開情報の照合）を付ける（既定: 有効）。"""
    raw = os.getenv("TRUTH_ASSESSMENT_GROUNDING", "1")
    v = (raw or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _pick_api_key() -> Optional[str]:
    """
    まず m03 のローテータ（GOOGLE_API_KEY_1,2,... と API_KEY_RANGE 等）から取得。
    キーが無い／未設定のときは GOOGLE_API_KEY または GOOGLE_API_KEY_n を直接参照。
    """
    key = api_key_manager.get_next_key_sync()
    if key:
        return key
    for env_name in (
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEY_1",
        "GOOGLE_API_KEY_2",
        "GOOGLE_API_KEY_3",
        "GOOGLE_API_KEY_4",
        "GOOGLE_API_KEY_5",
        "GOOGLE_API_KEY_6",
        "GOOGLE_API_KEY_7",
        "GOOGLE_API_KEY_8",
        "GOOGLE_API_KEY_9",
        "GOOGLE_API_KEY_10",
    ):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value
    return None


def _transient_gemini_error(err: BaseException) -> bool:
    """レート制限・一時障害など、待機やキー切替えで再試行しうるエラー。"""
    msg = f"{type(err).__name__}: {err}".lower()
    return any(
        part in msg
        for part in (
            "429",
            "resource exhausted",
            "rate limit",
            "quota",
            "too many requests",
            "503",
            "unavailable",
        )
    )


def _should_try_next_api_key(err: BaseException) -> bool:
    """複数キーがあるとき、別キーへの切り替えを試すか。"""
    if api_key_manager.key_count <= 1:
        return False
    return _transient_gemini_error(err)


def _gemini_max_api_retries() -> int:
    """同一モデル内の最大試行回数（429 等で指数バックオフまたはキー切替え）。環境変数 GEMINI_MAX_API_RETRIES（既定 5）。"""
    try:
        v = int((os.getenv("GEMINI_MAX_API_RETRIES") or "5").strip())
        return max(1, v)
    except ValueError:
        return 5


def _is_429_or_503_gemini_error(err: BaseException) -> bool:
    """429 / 503 を返したときのみ GEMINI_RETRY_MIN_DELAY_SEC を適用する。"""
    msg = f"{type(err).__name__}: {err}".lower()
    return "429" in msg or "503" in msg


def _gemini_retry_min_delay_sec() -> int:
    """429/503 の再試行前に最低待つ秒数。GEMINI_RETRY_MIN_DELAY_SEC（未設定・不正時は 0）。"""
    try:
        v = int((os.getenv("GEMINI_RETRY_MIN_DELAY_SEC") or "0").strip())
        return max(0, v)
    except ValueError:
        return 0


def _truth_json_parse_max_attempts() -> int:
    """真実度: 同一戦略で『応答あり・JSON 解釈失敗』のときの再試行回数（GEMINI_TRUTH_JSON_PARSE_RETRIES、既定 3、最低 1）。"""
    try:
        v = int((os.getenv("GEMINI_TRUTH_JSON_PARSE_RETRIES") or "3").strip())
        return max(1, v)
    except ValueError:
        return 3


def _truth_parse_retry_delay_sec() -> float:
    """真実度 JSON 再試行前の待機秒（GEMINI_TRUTH_PARSE_RETRY_DELAY_SEC、既定 0）。"""
    try:
        v = float((os.getenv("GEMINI_TRUTH_PARSE_RETRY_DELAY_SEC") or "0").strip())
        return max(0.0, v)
    except ValueError:
        return 0.0


def _extract_json_object(s: str) -> Optional[str]:
    """先頭以降の最初の { … } 対（文字列内の括弧に配慮）を抜き出す。"""
    t = s.strip()
    if not t:
        return None
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return t[start : i + 1]
    return None


def _clean_reason_text(s: str) -> str:
    """reason 内のよくある Markdown を除去（メール/プレーン向け）。"""
    t = s.replace("**", "").replace("__", "")
    t = re.sub(r"`+[^`]*`+", "", t)
    t = re.sub(r"#{1,6}\s*", "", t)
    return t.strip()


def _parse_truth_json(raw: str) -> tuple[Optional[int], str]:
    """モデルが返した JSON から score_percent / reason を取り出す。"""
    t = (raw or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t, flags=re.DOTALL)
    blobs: list[str] = []
    for b in (t, _extract_json_object(t) or ""):
        if b and b not in blobs:
            blobs.append(b)
    for blob in blobs:
        try:
            data = json.loads(blob)
            sc = int(data.get("score_percent", data.get("score", -1)))
            reason = _clean_reason_text(str(data.get("reason", "")).strip())
            if 0 <= sc <= 100:
                return sc, reason or "（理由の記載がありません。）"
        except (json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return None, (t[:1500] + ("…" if len(t) > 1500 else "")) if t else "（空の応答）"


def _truth_search_tag(grounding_enabled: bool) -> str:
    """真実度ブロック行末に付ける。TRUTH_ASSESSMENT_GROUNDING のオン／オフ。"""
    return f" [GoogleSearch:{'ON' if grounding_enabled else 'OFF'}]"


def _format_truth_block(
    score: Optional[int], reason: str, *, grounding_enabled: bool
) -> str:
    tag = _truth_search_tag(grounding_enabled)
    if score is not None:
        return (
            f"【この要約の真実度（目安）】 約{score}%{tag}\n"
            f"（根拠のメモ）{reason}\n"
            f"\n---\n\n"
        )
    return (
        f"【この要約の真実度（目安）】 数値化できませんでした（下記は API の生応答抜粋）{tag}\n"
        f"（抜粋）{reason}\n"
        f"\n---\n\n"
    )


def _truth_strategy_order(want_grounding: bool) -> list[tuple[str, bool, bool, bool]]:
    """
    真実度 API の試行順
    (label, use_google_search, use_api_json_schema, relaxed_prompt)。
    検索+API-JSON は 400 になりやすいため、先頭は検索+プロンプト JSON のみ（MIME/スキーマなし）。
    """
    s: list[tuple[str, bool, bool, bool]] = []
    if want_grounding:
        s.append(("真実度[検索+プロンプトJSON]", True, False, False))
    s.append(("真実度[JSONのみ]", False, True, False))
    if want_grounding:
        s.append(("真実度[検索・自由形式]", True, False, True))
    s.append(("真実度[自由形式]", False, False, True))
    return s


def _run_truth_with_strategies(
    api_key: str,
    models: tuple[str, ...],
    video_title: str,
    video_url: str,
    transcript_text: str,
    want_grounding: bool,
) -> tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    戻り値: (生テキスト, 最後の api_key, 成功時の戦略ラベル, 成功時のモデル名)
    パース可能な score が得られるまで戦略を変える。
    """
    key = api_key
    for label, use_gs, use_api_json, relaxed in _truth_strategy_order(want_grounding):
        print(f"{label} で試行 : ({PYTHON_NAME})")
        if relaxed:
            t_prompt = build_truth_assessment_prompt_relaxed(video_title, video_url)
        else:
            t_prompt = build_truth_assessment_prompt(
                video_title,
                video_url,
                json_via_api_schema=use_api_json,
            )
        t_parts = [t_prompt, "\n\n--- 文字起こし全文 ---\n", transcript_text]
        max_parse_tries = _truth_json_parse_max_attempts()
        parse_retry_delay = _truth_parse_retry_delay_sec()
        for parse_attempt in range(max_parse_tries):
            raw, key, model = _gemini_generate_loop(
                key,
                models,
                t_parts,
                temperature=0.1,
                max_output_tokens=2048,
                purpose=label,
                use_google_search_grounding=use_gs,
                response_mime_type="application/json" if use_api_json else None,
                response_json_schema=_TRUTH_JSON_SCHEMA if use_api_json else None,
            )
            if not raw:
                break
            if _parse_truth_json(raw)[0] is not None:
                return raw, key, label, model
            last_attempt = parse_attempt >= max_parse_tries - 1
            if not last_attempt:
                print(
                    f"警告: {label} は応答したが JSON 解釈に失敗。"
                    f"同一戦略で再試行 ({parse_attempt + 2}/{max_parse_tries}) : ({PYTHON_NAME})"
                )
                if parse_retry_delay > 0:
                    time.sleep(parse_retry_delay)
            elif not relaxed:
                print(
                    f"警告: {label} は応答したが JSON 解釈に失敗。次手順へ。 : ({PYTHON_NAME})"
                )
    return None, key, None, None


def _gemini_generate_loop(
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
) -> tuple[Optional[str], str, Optional[str]]:
    """Gemini 呼び出し。戻り値: (本文テキスト, 最後に使った api_key, 成功時の model 名)。"""
    extra_tools: list = []
    if use_google_search_grounding:
        try:
            extra_tools = [types.Tool(google_search=types.GoogleSearch())]
        except Exception as e:
            print(
                f"警告: Google 検索ツールを組み立てられません: {e}。検索なしで続行します。 : ({PYTHON_NAME})"
            )
    last_err: Optional[BaseException] = None
    max_attempts = _gemini_max_api_retries()
    for idx, model in enumerate(models):
        per_try = 0
        while per_try < max_attempts:
            try:
                client = genai.Client(api_key=api_key)
                gcfg: dict = {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                }
                if extra_tools:
                    gcfg["tools"] = extra_tools
                if response_mime_type:
                    gcfg["response_mime_type"] = response_mime_type
                if response_json_schema is not None:
                    gcfg["response_json_schema"] = response_json_schema
                response = client.models.generate_content(
                    model=model,
                    contents=parts,
                    config=types.GenerateContentConfig(**gcfg),
                )
                text = (getattr(response, "text", None) or "").strip()
                if text:
                    if idx > 0:
                        print(
                            f"{purpose}: フォールバック model={model} で成功 : ({PYTHON_NAME})"
                        )
                    return text, api_key, model
                print(
                    f"警告: {purpose} 応答が空（model={model}） : ({PYTHON_NAME})"
                )
                break
            except Exception as e:
                last_err = e
                per_try += 1
                if per_try >= max_attempts:
                    print(
                        f"警告: {purpose} が {max_attempts} 回失敗（model={model}）: {e} : ({PYTHON_NAME})"
                    )
                    break
                rotated = False
                if _should_try_next_api_key(e):
                    next_key = api_key_manager.get_next_key_sync()
                    if next_key and next_key != api_key:
                        api_key = next_key
                        rotated = True
                        print(
                            f"{purpose}: キー切替え再試行 ({per_try}/{max_attempts}) model={model}: {e} : ({PYTHON_NAME})"
                        )
                        _md = _gemini_retry_min_delay_sec()
                        if _md > 0 and _is_429_or_503_gemini_error(e):
                            print(
                                f"{purpose}: 429/503 再試行前 {_md}s 待機（キー切替え後） : ({PYTHON_NAME})"
                            )
                            time.sleep(_md)
                if not rotated and _transient_gemini_error(e):
                    exp = min(2 ** (per_try - 1), 45)
                    _md = _gemini_retry_min_delay_sec() if _is_429_or_503_gemini_error(e) else 0
                    delay = max(_md, exp) if _md > 0 else exp
                    print(
                        f"{purpose}: {delay}s 待機して再試行 ({per_try}/{max_attempts}) model={model}: {e} : ({PYTHON_NAME})"
                    )
                    time.sleep(delay)
                elif not rotated:
                    print(
                        f"警告: {purpose} に失敗（model={model}）: {e} : ({PYTHON_NAME})"
                    )
                    break
        if idx < len(models) - 1:
            print(
                f"{purpose}: モデル {model} を打ち切り、次へ切替 : ({PYTHON_NAME})"
            )
    if last_err:
        print(
            f"警告: 全モデルで {purpose} に失敗: {last_err} : ({PYTHON_NAME})"
        )
    return None, api_key, None


def generate_summary_to_file(
    transcript_text: str,
    output_path: str,
    *,
    prompt_mode: str,
    prompt_text: str,
    video_title: str,
    video_url: str,
    include_truth_assessment: bool = True,
) -> SummaryToFileResult:
    """
    文字起こしを Gemini で要約し output_path へ保存。
    先頭行にタイトル・URL、その後に（真実度を付ける場合は）「約◯% [GoogleSearch:ON|OFF]」と根拠メモ、本文は要約。
    include_truth_assessment が True のとき、先に要約前の全文で真実度（目安）を取得し、
    要約の直前に真実度ブロックを挿入する（真実度は戦略・モデルフォールバックあり）。
    戻り値は SummaryToFileResult（要約・真実度の成功状況と使用モデル名。パイプライン末尾ログ用）。
    """
    truth_label: Optional[str] = None
    truth_model: Optional[str] = None
    truth_ok = False
    truth_requested = include_truth_assessment

    if not (transcript_text or "").strip():
        return SummaryToFileResult(
            False, None, include_truth_assessment, False, None, None
        )
    api_key = _pick_api_key()
    if not api_key:
        print(f"警告: Gemini APIキーが見つからないため summary.txt をスキップします。 : ({PYTHON_NAME})")
        return SummaryToFileResult(
            False, None, include_truth_assessment, False, None, None
        )

    summary_models = _summary_model_chain()
    truth_models = _truth_model_chain()
    print(f"要約 Gemini モデル試行順: {', '.join(summary_models)} : ({PYTHON_NAME})")
    print(f"真実度 Gemini モデル試行順: {', '.join(truth_models)} : ({PYTHON_NAME})")

    truth_block = ""
    if include_truth_assessment:
        use_search = _truth_assessment_grounding_enabled()
        if use_search:
            print(
                f"真実度（目安）— 検索＋JSON 等、複数手順にフォールバック可 : ({PYTHON_NAME})"
            )
        else:
            print(
                f"真実度（目安）— TRUTH_ASSESSMENT_GROUNDING=0（検索なし・JSON 優先）: ({PYTHON_NAME})"
            )
        t_raw, api_key, truth_label, truth_model = _run_truth_with_strategies(
            api_key,
            truth_models,
            video_title,
            video_url,
            transcript_text,
            use_search,
        )
        truth_ok = bool(t_raw)
        if t_raw:
            sc, rsn = _parse_truth_json(t_raw)
            truth_block = _format_truth_block(sc, rsn, grounding_enabled=use_search)
        else:
            tag = _truth_search_tag(use_search)
            truth_block = (
                f"【この要約の真実度（目安）】 自動評価に失敗しました{tag}\n"
                f"（要約は続行します。）\n"
                f"\n---\n\n"
            )

    prompt = build_prompt(prompt_mode, prompt_text, video_title, video_url)
    s_parts = [prompt, "\n\n--- 文字起こし本文 ---\n", transcript_text]
    print(f"要約 : ({PYTHON_NAME})")
    body, api_key, summary_model = _gemini_generate_loop(
        api_key,
        summary_models,
        s_parts,
        temperature=0.2,
        max_output_tokens=12000,
        purpose="要約",
    )
    if not body:
        return SummaryToFileResult(
            ok=False,
            summary_model=None,
            truth_requested=truth_requested,
            truth_ok=truth_ok,
            truth_strategy_label=truth_label,
            truth_model=truth_model,
        )

    header = f"タイトル：{video_title}\nURL：{video_url}\n\n"
    out = header + truth_block + body
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(out)
    try:
        api_key_manager.save_session()
    except Exception as se:
        print(
            f"警告: API キーセッションの保存に失敗: {se} : ({PYTHON_NAME})"
        )
    return SummaryToFileResult(
        ok=True,
        summary_model=summary_model,
        truth_requested=truth_requested,
        truth_ok=truth_ok,
        truth_strategy_label=truth_label,
        truth_model=truth_model,
    )
