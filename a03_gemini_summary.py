#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a03 — ステップ2: 文字起こしを Gemini で要約し summary.txt へ（単体実行可）
    処理順: (1) financial 要約 + reference_sources 注入 → (2) 要約文ベースの軽量真実度（検索+JSON、失敗 OK）。
    真実度: モデル最大2・リトライ1・間隔5秒・要約後30秒待機・真実度は次キーから・リトライ毎キー切替が既定。
    前: a01 で transcript.txt 作成。a02 のプロンプトを import。次: a04 メール。
    API キーは m03_api_key_manager（ローテーション・.session_data.json 永続化）を優先利用。
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from typing import Any, NamedTuple, Optional

from google import genai
from google.genai import types

from a02_category_detect import (
    build_reference_prompt_block,
    detect_categories_for_summary,
)
from a02_summary_prompt_shared import (
    build_prompt,
    build_truth_assessment_prompt_for_summary,
)

from m03_api_key_manager import api_key_manager

# 要約: 既定のモデル試行順（m03_gemini_model_fallback 未導入時、または要約専用）
_DEFAULT_SUMMARY_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
)

_DEFAULT_TRUTH_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
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
            chain = parts
        else:
            chain = _DEFAULT_TRUTH_MODELS
    else:
        chain = _DEFAULT_TRUTH_MODELS
    try:
        n = int((os.getenv("GEMINI_TRUTH_MAX_MODELS") or "2").strip())
        n = max(1, n)
    except ValueError:
        n = 2
    return chain[:n]


def _truth_fallback_on_search_fail() -> bool:
    """検索+真実度失敗時に JSON のみ等へ落とすか（既定: オフ）。"""
    raw = (os.getenv("TRUTH_FALLBACK_ON_SEARCH_FAIL") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _truth_attempts_per_model() -> int:
    """真実度: 1 モデルあたりの API 試行回数（初回+リトライ。GEMINI_TRUTH_MAX_RETRIES=1 → 計2回）。"""
    try:
        extra = int((os.getenv("GEMINI_TRUTH_MAX_RETRIES") or "1").strip())
        return max(1, 1 + extra)
    except ValueError:
        return 2


def _truth_retry_delay_sec() -> float:
    try:
        v = float((os.getenv("GEMINI_TRUTH_RETRY_DELAY_SEC") or "5").strip())
        return max(0.0, v)
    except ValueError:
        return 5.0


def _truth_delay_after_summary_sec() -> float:
    """要約成功後、真実度開始前の待機秒（TRUTH_DELAY_AFTER_SUMMARY_SEC、既定 30）。"""
    try:
        v = float((os.getenv("TRUTH_DELAY_AFTER_SUMMARY_SEC") or "30").strip())
        return max(0.0, v)
    except ValueError:
        return 30.0


def _truth_verbose_request_log() -> bool:
    """真実度 API の入出力・エラー診断ログ（TRUTH_VERBOSE_REQUEST_LOG、既定: 有効）。"""
    raw = (os.getenv("TRUTH_VERBOSE_REQUEST_LOG") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _truth_always_rotate_key() -> bool:
    """真実度フェーズでリトライ・モデル切替のたびにキーを進める（既定: 有効）。"""
    raw = (os.getenv("TRUTH_ALWAYS_ROTATE_KEY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _truth_max_key_rotations() -> int | None:
    """
    真実度のキー切替上限。TRUTH_ALWAYS_ROTATE_KEY=1 のときは無制限（None）。
    0 指定時のみ GEMINI_TRUTH_MAX_KEY_ROTATIONS を参照（後方互換）。
    """
    if _truth_always_rotate_key():
        return None
    try:
        return max(0, int((os.getenv("GEMINI_TRUTH_MAX_KEY_ROTATIONS") or "0").strip()))
    except ValueError:
        return 0


def _max_project_restricted_key_skips() -> int:
    """
    404（new users 等・プロジェクト制限）のとき同一モデルで試すキー数上限。
    TRUTH_MAX_PROJECT_RESTRICTED_KEY_SKIPS 未設定時はロード済み全キー。
    """
    try:
        v = int((os.getenv("TRUTH_MAX_PROJECT_RESTRICTED_KEY_SKIPS") or "0").strip())
        if v > 0:
            return v
    except ValueError:
        pass
    n = api_key_manager.key_count
    return max(1, n)

PYTHON_NAME = os.path.basename(__file__)


class SummaryToFileResult(NamedTuple):
    """generate_summary_to_file の戻り値。パイプライン末尾のサマリ行用。"""

    ok: bool
    summary_model: Optional[str]
    truth_requested: bool
    truth_ok: bool
    truth_strategy_label: Optional[str]
    truth_model: Optional[str]


class GroundingInfo(NamedTuple):
    """generateContent 応答の grounding_metadata から抽出した情報。"""

    search_used: bool
    web_search_queries: tuple[str, ...]
    grounding_chunk_count: int
    grounding_support_count: int
    source_urls: tuple[str, ...]


class GeminiGenerateResult(NamedTuple):
    """_gemini_generate_loop の戻り値。"""

    text: Optional[str]
    api_key: str
    model: Optional[str]
    grounding: GroundingInfo


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


def _parts_to_text(parts: list) -> str:
    """Gemini contents 用 parts リストを連結テキストに。"""
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, str):
            chunks.append(p)
        else:
            chunks.append(str(p))
    return "".join(chunks)


def _estimate_tokens(text: str) -> int:
    """
    入力トークン数の目安（API 公式値ではない）。
    日本語混在を想定し、おおよそ 1 トークン ≒ 2 文字。
    """
    n = len(text or "")
    if n <= 0:
        return 0
    return max(1, (n + 1) // 2)


def _truth_input_breakdown(parts: list) -> dict[str, int]:
    """真実度用 parts [prompt, sep, summary] の文字数内訳。"""
    if len(parts) >= 3 and isinstance(parts[0], str) and isinstance(parts[2], str):
        prompt_chars = len(parts[0])
        summary_chars = len(parts[2])
        sep_chars = sum(len(p) for p in parts[1:-1] if isinstance(p, str))
        return {
            "prompt_chars": prompt_chars,
            "summary_chars": summary_chars,
            "separator_chars": sep_chars,
        }
    total = len(_parts_to_text(parts))
    return {"prompt_chars": total, "summary_chars": 0, "separator_chars": 0}


def _format_request_stats(parts: list, *, max_output_tokens: int) -> str:
    text = _parts_to_text(parts)
    total_chars = len(text)
    est_in = _estimate_tokens(text)
    breakdown = _truth_input_breakdown(parts)
    if breakdown["summary_chars"] > 0:
        return (
            f"入力 合計{total_chars}字~{est_in}tok(推定) "
            f"(プロンプト{breakdown['prompt_chars']}字+要約{breakdown['summary_chars']}字) "
            f"max_out={max_output_tokens}"
        )
    return f"入力 合計{total_chars}字~{est_in}tok(推定) max_out={max_output_tokens}"


def _parse_gemini_error_payload(err: BaseException) -> dict[str, Any]:
    """Gemini 例外文字列から error オブジェクトを抽出。"""
    text = str(err)
    start = text.find("{")
    if start < 0:
        return {"raw": text}
    try:
        blob = ast.literal_eval(text[start:])
        if isinstance(blob, dict):
            err_obj = blob.get("error", blob)
            if isinstance(err_obj, dict):
                return {
                    "code": err_obj.get("code"),
                    "status": err_obj.get("status"),
                    "message": str(err_obj.get("message") or ""),
                    "details": err_obj.get("details") or [],
                }
    except (SyntaxError, ValueError, TypeError):
        pass
    return {"raw": text}


def _extract_error_info_metadata(details: list) -> dict[str, str]:
    meta: dict[str, str] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        if "ErrorInfo" not in str(item.get("@type", "")):
            continue
        reason = item.get("reason")
        if reason:
            meta["reason"] = str(reason)
        raw_meta = item.get("metadata") or {}
        if isinstance(raw_meta, dict):
            for k, v in raw_meta.items():
                meta[str(k)] = str(v)
    return meta


def _gemini_model_project_restricted_error(err: BaseException) -> bool:
    """404 だがモデル自体は存在し、この API キー（プロジェクト）だけ使えないケース。"""
    msg = str(err).lower()
    return any(
        part in msg
        for part in (
            "no longer available to new users",
            "not available to new users",
        )
    )


def _gemini_model_not_found_error(err: BaseException) -> bool:
    """モデル名が API 全体で無効（存在しない・generateContent 非対応）。"""
    if _gemini_model_project_restricted_error(err):
        return False
    payload = _parse_gemini_error_payload(err)
    if payload.get("code") == 404 or payload.get("status") == "NOT_FOUND":
        return True
    msg = str(err).lower()
    return "not found" in msg and "models/" in msg


def _diagnose_gemini_error(
    err: BaseException,
    *,
    model: str,
    purpose: str,
) -> list[str]:
    """人間向けのエラー原因行（ログ用）。"""
    payload = _parse_gemini_error_payload(err)
    lines: list[str] = []
    code = payload.get("code")
    status = payload.get("status")
    message = (payload.get("message") or str(err)).strip()
    if len(message) > 280:
        message = message[:277] + "…"
    lines.append(f"  種別: {type(err).__name__} code={code} status={status}")
    lines.append(f"  APIメッセージ: {message}")

    meta = _extract_error_info_metadata(payload.get("details") or [])
    if meta.get("reason"):
        lines.append(f"  reason: {meta['reason']}")
    quota_keys = (
        "quota_metric",
        "quota_limit",
        "quota_location",
        "quota_limit_value",
        "quota_unit",
        "consumer",
        "service",
    )
    quota_parts = [f"{k}={meta[k]}" for k in quota_keys if meta.get(k)]
    if quota_parts:
        lines.append(f"  クォータ: {', '.join(quota_parts)}")

    if _gemini_model_project_restricted_error(err):
        lines.append(
            f"  診断: モデル `{model}` は **この API キー（プロジェクト）では利用不可**。"
            " 別 GOOGLE_API_KEY_n では使える場合があります（テストと batch でキー番号が違うと結果が変わります）。"
            " **キー切替を推奨**（モデル列の変更では解決しない場合あり）。"
        )
    elif _gemini_model_not_found_error(err):
        lines.append(
            f"  診断: モデル `{model}` が API 全体で generateContent 非対応または存在しません。"
            " GEMINI_TRUTH_MODELS / 要約モデル列を確認してください。"
            " キー切替・待機では解決しません。"
        )
    elif code == 429 or status == "RESOURCE_EXHAUSTED":
        if meta.get("reason") == "RATE_LIMIT_EXCEEDED":
            loc = meta.get("quota_location", "?")
            limit = meta.get("quota_limit", "?")
            lines.append(
                f"  診断: 分あたりリクエスト上限（地域 {loc}, {limit}）。"
                " 待機・キー切替で改善する場合があります（同一プロジェクトなら上限共有）。"
            )
        else:
            lines.append(
                "  診断: クォータ超過（日次上限・課金プラン等）。"
                " 全キーが同一プロジェクトなら切替だけでは解消しない可能性があります。"
            )
    elif _gemini_invalid_api_key_error(err):
        lines.append("  診断: APIキー無効。別 GOOGLE_API_KEY_n への切替を推奨。")
    elif _gemini_permission_denied_error(err):
        lines.append(
            "  診断: 権限拒否（403）。プロジェクト拒否の場合は別 GOOGLE_API_KEY_n への切替を推奨。"
        )
    elif code == 400:
        lines.append("  診断: リクエスト内容の問題。入力サイズ・ツール設定を確認。")
    else:
        lines.append(f"  診断: {purpose} の再試行可否はエラー種別次第（上記参照）。")

    return lines


def _log_gemini_error_diagnosis(
    err: BaseException,
    *,
    purpose: str,
    model: str,
    key_label: str,
    request_stats: str,
) -> None:
    """真実度向け: 構造化エラー診断を出力。"""
    print(
        f"警告: {purpose} 失敗 model={model} {key_label} | {request_stats} : ({PYTHON_NAME})"
    )
    for line in _diagnose_gemini_error(err, model=model, purpose=purpose):
        print(f"{purpose}{line} : ({PYTHON_NAME})")


def _log_response_usage(response: Any, *, purpose: str, key_label: str) -> None:
    """成功応答の usage_metadata をログ（取得できた場合のみ）。"""
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return
    prompt_t = getattr(um, "prompt_token_count", None)
    cand_t = getattr(um, "candidates_token_count", None)
    total_t = getattr(um, "total_token_count", None)
    if prompt_t is None and cand_t is None and total_t is None:
        return
    parts = []
    if prompt_t is not None:
        parts.append(f"prompt={prompt_t}tok")
    if cand_t is not None:
        parts.append(f"output={cand_t}tok")
    if total_t is not None:
        parts.append(f"total={total_t}tok")
    print(
        f"{purpose}: usage {', '.join(parts)} {key_label} : ({PYTHON_NAME})"
    )


def _empty_grounding_info() -> GroundingInfo:
    return GroundingInfo(False, (), 0, 0, ())


def _parse_grounding_from_response(response: Any) -> GroundingInfo:
    """
    generateContent 応答から grounding_metadata を解析（公式 generateContent API 形式）。
    検索実行の目安: web_search_queries / grounding_chunks / grounding_supports のいずれか。
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return _empty_grounding_info()
    gm = getattr(candidates[0], "grounding_metadata", None)
    if gm is None:
        return _empty_grounding_info()

    queries: list[str] = []
    for attr in ("web_search_queries", "retrieval_queries", "image_search_queries"):
        for q in getattr(gm, attr, None) or []:
            s = str(q or "").strip()
            if s and s not in queries:
                queries.append(s)

    chunks = getattr(gm, "grounding_chunks", None) or []
    supports = getattr(gm, "grounding_supports", None) or []

    urls: list[str] = []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web is None:
            continue
        uri = getattr(web, "uri", None)
        if uri:
            u = str(uri).strip()
            if u and u not in urls:
                urls.append(u)

    search_used = bool(queries or chunks or supports)
    return GroundingInfo(
        search_used=search_used,
        web_search_queries=tuple(queries),
        grounding_chunk_count=len(chunks),
        grounding_support_count=len(supports),
        source_urls=tuple(urls[:8]),
    )


def _log_grounding_info(
    info: GroundingInfo,
    *,
    purpose: str,
    key_label: str,
    tool_requested: bool,
) -> None:
    """grounding_metadata の要約をログ。GoogleSearch=ON/OFF は API 応答ベース。"""
    status = "ON" if info.search_used else "OFF"
    if info.web_search_queries:
        q_text = ", ".join(repr(q) for q in info.web_search_queries[:4])
        if len(info.web_search_queries) > 4:
            q_text += f" …他{len(info.web_search_queries) - 4}件"
        queries_part = f" queries=[{q_text}]"
    else:
        queries_part = " queries=なし"
    meta_part = (
        f" chunks={info.grounding_chunk_count}"
        f" supports={info.grounding_support_count}"
    )
    print(
        f"{purpose}: grounding GoogleSearch={status}{queries_part}{meta_part} "
        f"{key_label} : ({PYTHON_NAME})"
    )
    if info.source_urls:
        for i, url in enumerate(info.source_urls[:5], 1):
            print(f"{purpose}:  grounding source#{i} {url} : ({PYTHON_NAME})")
        if len(info.source_urls) > 5:
            print(
                f"{purpose}:  grounding …他{len(info.source_urls) - 5}件の source : ({PYTHON_NAME})"
            )
    if tool_requested and not info.search_used:
        print(
            f"{purpose}:  診断: google_search ツール付きだが grounding_metadata に検索痕跡なし"
            f"（モデルが検索不要と判断した可能性） : ({PYTHON_NAME})"
        )
    elif info.search_used and info.grounding_support_count > 0:
        print(
            f"{purpose}:  grounding_supports={info.grounding_support_count} 件"
            f"（引用マッピングあり） : ({PYTHON_NAME})"
        )


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


def _gemini_invalid_api_key_error(err: BaseException) -> bool:
    """無効・期限切れなど、別の GOOGLE_API_KEY_n が有効なら切り替えて再試行しうるエラー。"""
    msg = f"{type(err).__name__}: {err}".lower()
    return any(
        part in msg
        for part in (
            "api key expired",
            "api_key_invalid",
            "invalid api key",
        )
    )


def _gemini_permission_denied_error(err: BaseException) -> bool:
    """403 / PERMISSION_DENIED。プロジェクト拒否など別キーで解消しうる。"""
    payload = _parse_gemini_error_payload(err)
    if payload.get("code") == 403 or payload.get("status") == "PERMISSION_DENIED":
        return True
    msg = f"{type(err).__name__}: {err}".lower()
    return "permission_denied" in msg or "permission denied" in msg


def _should_try_next_api_key(err: BaseException) -> bool:
    """複数キーがあるとき、別キーへの切り替えを試すか。"""
    if api_key_manager.key_count <= 1:
        return False
    return (
        _transient_gemini_error(err)
        or _gemini_invalid_api_key_error(err)
        or _gemini_permission_denied_error(err)
    )


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
    """真実度: 同一戦略で『応答あり・JSON 解釈失敗』のときの再試行回数（GEMINI_TRUTH_JSON_PARSE_RETRIES、既定 1）。"""
    try:
        v = int((os.getenv("GEMINI_TRUTH_JSON_PARSE_RETRIES") or "1").strip())
        return max(1, v)
    except ValueError:
        return 1


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


def _truth_search_tag(*, search_used: bool) -> str:
    """真実度ブロック行末。検索が実際に成功したときのみ ON。"""
    return f" [GoogleSearch:{'ON' if search_used else 'OFF'}]"


def _format_truth_block(
    score: Optional[int], reason: str, *, search_used: bool
) -> str:
    tag = _truth_search_tag(search_used=search_used)
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


def _format_truth_failure_block() -> str:
    return (
        "【真実度確認】 失敗\n"
        "※要約本文は作成済みです。制度・数値の最新情報は各公式サイトでご確認ください。\n"
        "\n---\n\n"
    )


def _run_truth_on_summary(
    api_key: str,
    models: tuple[str, ...],
    video_title: str,
    video_url: str,
    summary_text: str,
    reference_block: str,
    *,
    want_grounding: bool,
) -> tuple[Optional[str], str, Optional[str], Optional[str], bool]:
    """
    要約文ベースの軽量真実度。
    戻り値: (生テキスト, api_key, 戦略ラベル, モデル名, 検索成功フラグ)
    """
    key = api_key
    strategies: list[tuple[str, bool, bool]] = []
    if want_grounding:
        strategies.append(("真実度[検索+プロンプトJSON]", True, False))
    if not want_grounding or _truth_fallback_on_search_fail():
        strategies.append(("真実度[JSONのみ]", False, True))

    max_parse_tries = _truth_json_parse_max_attempts()
    attempts_per_model = _truth_attempts_per_model()
    retry_delay = _truth_retry_delay_sec()
    max_rotations = _truth_max_key_rotations()
    always_rotate = _truth_always_rotate_key()
    verbose = _truth_verbose_request_log()

    for label, use_gs, use_api_json in strategies:
        print(f"{label} で試行（モデル列: {', '.join(models)}） : ({PYTHON_NAME})")
        t_prompt = build_truth_assessment_prompt_for_summary(
            video_title, video_url, reference_block=reference_block
        )
        t_parts = [t_prompt, "\n\n--- 要約文 ---\n", summary_text]
        if verbose:
            stats = _format_request_stats(t_parts, max_output_tokens=2048)
            tools_note = "GoogleSearch=ON" if use_gs else "GoogleSearch=OFF"
            json_note = "response=JSON" if use_api_json else "response=text"
            print(
                f"{label}: リクエスト概要 {stats} | {tools_note} | {json_note} "
                f"| 要約文{len(summary_text)}字 : ({PYTHON_NAME})"
            )
        for parse_attempt in range(max_parse_tries):
            if always_rotate and parse_attempt > 0:
                next_key = api_key_manager.get_next_key_sync()
                if next_key:
                    print(
                        f"{label}: JSON再試行前 キー切替 → "
                        f"{api_key_manager.format_key_log(api_key=next_key)} : ({PYTHON_NAME})"
                    )
                    key = next_key
            gen = _gemini_generate_loop(
                key,
                models,
                t_parts,
                temperature=0.1,
                max_output_tokens=2048,
                purpose=label,
                use_google_search_grounding=use_gs,
                response_mime_type="application/json" if use_api_json else None,
                response_json_schema=_TRUTH_JSON_SCHEMA if use_api_json else None,
                max_attempts_override=attempts_per_model,
                retry_delay_sec_override=retry_delay,
                max_key_rotations=max_rotations,
                always_rotate_key=always_rotate,
                verbose_request_log=verbose,
            )
            raw, key, model, grounding = (
                gen.text,
                gen.api_key,
                gen.model,
                gen.grounding,
            )
            if not raw:
                break
            if _parse_truth_json(raw)[0] is not None:
                gs_flag = "ON" if grounding.search_used else "OFF"
                print(
                    f"{label}: Gemini API 成功 model={model} "
                    f"GoogleSearch={gs_flag} : ({PYTHON_NAME})"
                )
                return raw, key, label, model, grounding.search_used
            last_attempt = parse_attempt >= max_parse_tries - 1
            if verbose and raw:
                preview = raw[:200].replace("\n", " ")
                print(
                    f"警告: {label} JSON解釈失敗 model={model} "
                    f"応答先頭200字={preview!r} : ({PYTHON_NAME})"
                )
            if not last_attempt:
                print(
                    f"警告: {label} は応答したが JSON 解釈に失敗 (model={model})。"
                    f"同一戦略で再試行 ({parse_attempt + 2}/{max_parse_tries}) : ({PYTHON_NAME})"
                )
            else:
                hint = "次手順へ" if _truth_fallback_on_search_fail() else "終了"
                print(
                    f"警告: {label} は応答したが JSON 解釈に失敗 (model={model})。{hint}。 : ({PYTHON_NAME})"
                )
        if not _truth_fallback_on_search_fail():
            break
    print(
        f"[真実度] 全戦略失敗 — 要約は成功。"
        f" 主因候補: 404=モデル名不正 / 429=クォータ・レート制限。"
        f" 上記の「診断:」行を参照 : ({PYTHON_NAME})"
    )
    return None, key, None, None, False


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
    max_attempts_override: Optional[int] = None,
    retry_delay_sec_override: Optional[float] = None,
    max_key_rotations: Optional[int] = None,
    always_rotate_key: bool = False,
    verbose_request_log: bool = False,
) -> GeminiGenerateResult:
    """Gemini 呼び出し。戻り値: 本文・api_key・model・grounding_metadata 解析結果。"""
    extra_tools: list = []
    if use_google_search_grounding:
        try:
            extra_tools = [types.Tool(google_search=types.GoogleSearch())]
        except Exception as e:
            print(
                f"警告: Google 検索ツールを組み立てられません: {e}。検索なしで続行します。 : ({PYTHON_NAME})"
            )
    last_err: Optional[BaseException] = None
    max_attempts = max_attempts_override if max_attempts_override is not None else _gemini_max_api_retries()
    key_rotations_done = 0
    total_calls = 0
    request_stats = _format_request_stats(parts, max_output_tokens=max_output_tokens)
    tools_label = "GoogleSearch" if extra_tools else "tools=なし"
    mime_label = response_mime_type or "text/plain"
    max_project_skips = _max_project_restricted_key_skips()
    for idx, model in enumerate(models):
        per_try = 0
        project_restricted_skips = 0
        while per_try < max_attempts:
            if always_rotate_key and total_calls > 0 and api_key_manager.key_count > 1:
                prev_label = api_key_manager.format_key_log(api_key=api_key)
                next_key = api_key_manager.get_next_key_sync()
                if next_key:
                    api_key = next_key
                    print(
                        f"{purpose}: キー切替 {prev_label} → "
                        f"{api_key_manager.format_key_log(api_key=api_key)} : ({PYTHON_NAME})"
                    )
            total_calls += 1
            key_label = api_key_manager.format_key_log(api_key=api_key)
            try:
                if verbose_request_log:
                    print(
                        f"{purpose}: 呼び出し準備 model={model} {key_label} "
                        f"({per_try + 1}/{max_attempts}) | {request_stats} | "
                        f"temp={temperature} {tools_label} mime={mime_label} : ({PYTHON_NAME})"
                    )
                else:
                    print(
                        f"{purpose}: Gemini API 呼び出し model={model} {key_label} "
                        f"({per_try + 1}/{max_attempts}) : ({PYTHON_NAME})"
                    )
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
                grounding = (
                    _parse_grounding_from_response(response)
                    if extra_tools
                    else _empty_grounding_info()
                )
                if text:
                    if verbose_request_log:
                        _log_response_usage(response, purpose=purpose, key_label=key_label)
                    if extra_tools:
                        _log_grounding_info(
                            grounding,
                            purpose=purpose,
                            key_label=key_label,
                            tool_requested=True,
                        )
                    print(
                        f"{purpose}: Gemini API 成功 model={model} {key_label} : ({PYTHON_NAME})"
                    )
                    return GeminiGenerateResult(text, api_key, model, grounding)
                print(
                    f"警告: {purpose} 応答が空（model={model} {key_label}）| {request_stats} : ({PYTHON_NAME})"
                )
                break
            except Exception as e:
                last_err = e
                if _gemini_model_project_restricted_error(e):
                    project_restricted_skips += 1
                    if verbose_request_log:
                        _log_gemini_error_diagnosis(
                            e,
                            purpose=purpose,
                            model=model,
                            key_label=key_label,
                            request_stats=request_stats,
                        )
                    else:
                        print(
                            f"警告: {purpose} プロジェクト制限404 model={model} {key_label} "
                            f"({project_restricted_skips}/{max_project_skips}): {e} : ({PYTHON_NAME})"
                        )
                    print(
                        f"{purpose}: モデル {model} は {key_label} では不可 → "
                        f"キー切替して同一モデルを継続 "
                        f"({project_restricted_skips}/{max_project_skips}) : ({PYTHON_NAME})"
                    )
                    if project_restricted_skips >= max_project_skips:
                        print(
                            f"{purpose}: モデル {model} を "
                            f"{max_project_skips} キーで試行もプロジェクト制限404 → 次モデルへ : ({PYTHON_NAME})"
                        )
                        break
                    continue

                per_try += 1
                if verbose_request_log:
                    _log_gemini_error_diagnosis(
                        e,
                        purpose=purpose,
                        model=model,
                        key_label=key_label,
                        request_stats=request_stats,
                    )
                elif per_try >= max_attempts:
                    print(
                        f"警告: {purpose} が {max_attempts} 回失敗（model={model} {key_label}）: {e} : ({PYTHON_NAME})"
                    )
                if _gemini_model_not_found_error(e):
                    print(
                        f"{purpose}: モデル {model} は API 全体で利用不可のため打ち切り : ({PYTHON_NAME})"
                    )
                    break
                if per_try >= max_attempts:
                    break
                rotated = False
                if not always_rotate_key:
                    allow_rotate = max_key_rotations is None or key_rotations_done < max_key_rotations
                    if allow_rotate and _should_try_next_api_key(e):
                        next_key = api_key_manager.get_next_key_sync()
                        if next_key and next_key != api_key:
                            api_key = next_key
                            rotated = True
                            key_rotations_done += 1
                            print(
                                f"{purpose}: キー切替え再試行 ({per_try}/{max_attempts}) model={model}: {e} : ({PYTHON_NAME})"
                            )
                if retry_delay_sec_override is not None and retry_delay_sec_override > 0:
                    if always_rotate_key or _is_429_or_503_gemini_error(e):
                        print(
                            f"{purpose}: {retry_delay_sec_override}s 待機して再試行 "
                            f"({per_try}/{max_attempts}) model={model} "
                            f"{api_key_manager.format_key_log(api_key=api_key)} : ({PYTHON_NAME})"
                        )
                        time.sleep(retry_delay_sec_override)
                elif not rotated and _transient_gemini_error(e):
                    if retry_delay_sec_override is not None and retry_delay_sec_override > 0:
                        delay = retry_delay_sec_override if _is_429_or_503_gemini_error(e) else min(
                            2 ** (per_try - 1), 45
                        )
                    else:
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
        if verbose_request_log:
            print(
                f"警告: 全モデルで {purpose} に失敗（最終） : ({PYTHON_NAME})"
            )
            for line in _diagnose_gemini_error(
                last_err, model=models[-1] if models else "?", purpose=purpose
            ):
                print(f"{purpose}{line} : ({PYTHON_NAME})")
        else:
            print(
                f"警告: 全モデルで {purpose} に失敗: {last_err} : ({PYTHON_NAME})"
            )
    return GeminiGenerateResult(None, api_key, None, _empty_grounding_info())


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
    処理順: (1) 要約（financial + reference_sources）→ (2) 要約文ベースの軽量真実度（任意）。
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

    # キーを1つでも進めたら成功・失敗を問わずセッションを残す（失敗時の同一キー連打を防ぐ）
    try:
        summary_models = _summary_model_chain()
        truth_models = _truth_model_chain()
        print(f"要約 Gemini モデル試行順: {', '.join(summary_models)} : ({PYTHON_NAME})")
        if include_truth_assessment:
            print(f"真実度 Gemini モデル試行順: {', '.join(truth_models)} : ({PYTHON_NAME})")

        categories = detect_categories_for_summary(video_title, transcript_text)
        if categories:
            print(f"要約カテゴリ判定: {', '.join(categories)} : ({PYTHON_NAME})")
        reference_block = build_reference_prompt_block(categories)

        prompt = build_prompt(
            prompt_mode,
            prompt_text,
            video_title,
            video_url,
            reference_block=reference_block,
        )
        s_parts = [prompt, "\n\n--- 文字起こし本文 ---\n", transcript_text]
        print(f"要約（モデル列: {', '.join(summary_models)}） : ({PYTHON_NAME})")
        summary_gen = _gemini_generate_loop(
            api_key,
            summary_models,
            s_parts,
            temperature=0.2,
            max_output_tokens=12000,
            purpose="要約",
        )
        body, api_key, summary_model = summary_gen.text, summary_gen.api_key, summary_gen.model
        if not body:
            return SummaryToFileResult(
                ok=False,
                summary_model=None,
                truth_requested=truth_requested,
                truth_ok=False,
                truth_strategy_label=None,
                truth_model=None,
            )

        summary_key_label = api_key_manager.format_key_log(api_key=api_key)
        print(f"要約: 使用キー {summary_key_label} : ({PYTHON_NAME})")

        truth_block = ""
        if include_truth_assessment:
            delay = _truth_delay_after_summary_sec()
            if delay > 0:
                print(
                    f"真実度開始前 {delay}s 待機（要約キー {summary_key_label} → 次キーへ） : ({PYTHON_NAME})"
                )
                time.sleep(delay)
            next_truth_key = api_key_manager.get_next_key_sync()
            if next_truth_key:
                api_key = next_truth_key
            print(
                f"真実度: 開始キー {api_key_manager.format_key_log(api_key=api_key)} : ({PYTHON_NAME})"
            )
            use_search = _truth_assessment_grounding_enabled()
            if use_search:
                print(
                    f"真実度（要約ベース）— 検索+JSON・モデル最大{len(truth_models)}・"
                    f"リトライ{_truth_attempts_per_model() - 1}・間隔{int(_truth_retry_delay_sec())}s・"
                    f"フォールバック={'ON' if _truth_fallback_on_search_fail() else 'OFF'} : ({PYTHON_NAME})"
                )
            else:
                print(
                    f"真実度（要約ベース）— TRUTH_ASSESSMENT_GROUNDING=0 : ({PYTHON_NAME})"
                )
            t_raw, api_key, truth_label, truth_model, search_used = _run_truth_on_summary(
                api_key,
                truth_models,
                video_title,
                video_url,
                body,
                reference_block,
                want_grounding=use_search,
            )
            truth_ok = bool(t_raw)
            if t_raw:
                sc, rsn = _parse_truth_json(t_raw)
                truth_block = _format_truth_block(sc, rsn, search_used=search_used)
            else:
                truth_block = _format_truth_failure_block()
                print(f"[真実度] 確認失敗（要約は成功） : ({PYTHON_NAME})")

        header = f"タイトル：{video_title}\nURL：{video_url}\n\n"
        out = header + truth_block + body
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(out)
        return SummaryToFileResult(
            ok=True,
            summary_model=summary_model,
            truth_requested=truth_requested,
            truth_ok=truth_ok,
            truth_strategy_label=truth_label,
            truth_model=truth_model,
        )
    finally:
        try:
            api_key_manager.save_session()
        except Exception as se:
            print(
                f"警告: API キーセッションの保存に失敗: {se} : ({PYTHON_NAME})"
            )
