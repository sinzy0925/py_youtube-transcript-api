#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Search グラウンディングの最小テスト（.env の GOOGLE_API_KEY_n を使用）。

  python test_grounding_search.py
  python test_grounding_search.py --key 4
  python test_grounding_search.py --all-keys
  python test_grounding_search.py --all-keys --models 2.0,2.5,3.1,3.5
  python test_grounding_search.py --all-keys --model gemini-2.5-flash-lite --delay 2
  python test_grounding_search.py --rotate --max-keys 3
  python test_grounding_search.py --query "2024年ノーベル物理学賞 受賞者"

要約パイプラインは走らせません。generateContent + google_search ツール（a03 と同方式）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import NamedTuple

from dotenv import load_dotenv
from google import genai
from google.genai import types

from a03_gemini_summary import (
    _diagnose_gemini_error,
    _gemini_model_project_restricted_error,
    _log_grounding_info,
    _log_response_usage,
    _parse_gemini_error_payload,
    _parse_grounding_from_response,
)
from m03_api_key_manager import api_key_manager

_DEFAULT_QUERY = "2024年のノーベル物理学賞の受賞者を1文で教えて。"
_DEFAULT_MODEL = "gemini-2.5-flash-lite"
_ALL_KEYS_MAX = 10

# --models 2.0,2.5,3.1,3.5 または --model-suite の既定列
_MODEL_SUITE: dict[str, tuple[str, ...]] = {
    "2.0": ("gemini-2.0-flash",),
    "2.5": ("gemini-2.5-flash-lite", "gemini-2.5-flash"),
    "3.1": ("gemini-3.1-flash-lite",),
    "3.5": ("gemini-3.5-flash-lite", "gemini-3.5-flash"),
}
_DEFAULT_SUITE_ORDER = ("2.0", "2.5", "3.1", "3.5")


def _short_model_label(model: str) -> str:
    m = model.removeprefix("gemini-")
    return m.replace("-flash-lite", "-lite").replace("-flash", "")


class KeyTestResult(NamedTuple):
    env_suffix: int
    key_label: str
    status: str
    detail: str
    elapsed_sec: float | None
    grounding_on: bool


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)


def _resolve_model(raw: str) -> str:
    return (raw or os.getenv("TEST_GROUNDING_MODEL") or _DEFAULT_MODEL).strip()


def _parse_models_arg(raw: str) -> list[str]:
    """'2.0,2.5,3.1,3.5' または 'gemini-2.5-flash-lite,gemini-3.5-flash-lite' を展開。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return []
    out: list[str] = []
    for p in parts:
        if p in _MODEL_SUITE:
            out.extend(_MODEL_SUITE[p])
        elif p.startswith("gemini-"):
            out.append(p)
        else:
            # gemini- なしのフル名
            out.append(f"gemini-{p}" if not p.startswith("gemini-") else p)
    # 重複除去（順序維持）
    seen: set[str] = set()
    unique: list[str] = []
    for m in out:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def _default_suite_models() -> list[str]:
    out: list[str] = []
    for tag in _DEFAULT_SUITE_ORDER:
        out.extend(_MODEL_SUITE[tag])
    return out


def _pick_key_by_env_suffix(suffix: int) -> str | None:
    """GOOGLE_API_KEY_N を .env から直接取得（ローテーションせず指定キーのみ）。"""
    val = (os.getenv(f"GOOGLE_API_KEY_{suffix}") or "").strip()
    return val or None


def _pick_key_rotate() -> str | None:
    return api_key_manager.get_next_key_sync()


def _key_label_for_suffix(suffix: int, api_key: str) -> str:
    label = api_key_manager.format_key_log(api_key=api_key)
    if f"GOOGLE_API_KEY_{suffix}" in label:
        return label
    return f"GOOGLE_API_KEY_{suffix} (…{api_key[-4:]})"


def _classify_error(err: BaseException) -> tuple[str, str]:
    payload = _parse_gemini_error_payload(err)
    code = payload.get("code")
    message = (payload.get("message") or str(err)).strip()
    if len(message) > 120:
        message = message[:117] + "…"
    if _gemini_model_project_restricted_error(err):
        return "404_PROJECT", message
    if code == 404:
        return "404", message
    if code == 429:
        return "429", message
    return "ERROR", message


def _list_loaded_keys() -> None:
    print(f"ロード済みキー: {api_key_manager.key_count} 個")
    for i in range(api_key_manager.key_count):
        label = api_key_manager.format_key_log(list_index=i)
        print(f"  [{i + 1}] {label}")


def _call_grounding(
    api_key: str,
    *,
    model: str,
    query: str,
) -> tuple[int, float | None, bool, str]:
    """
    1 回 API 呼び出し。
    戻り値: (exit_code, elapsed_sec, grounding_on, detail_or_response_preview)
    """
    tool = types.Tool(google_search=types.GoogleSearch())
    cfg = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=512,
        tools=[tool],
    )
    client = genai.Client(api_key=api_key)
    try:
        t0 = time.perf_counter()
        response = client.models.generate_content(
            model=model,
            contents=query,
            config=cfg,
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        status, detail = _classify_error(e)
        code = {"404_PROJECT": 1, "404": 1, "429": 1, "ERROR": 1}.get(status, 1)
        return code, None, False, f"{status}: {detail}"

    text = (getattr(response, "text", None) or "").strip()
    grounding = _parse_grounding_from_response(response)
    if not text:
        return 2, elapsed, grounding.search_used, "EMPTY: 応答テキストなし"
    preview = text.replace("\n", " ")
    if len(preview) > 80:
        preview = preview[:77] + "…"
    gs = "ON" if grounding.search_used else "OFF"
    qn = len(grounding.web_search_queries)
    detail = f"Grounding={gs} queries={qn} | {preview}"
    return 0, elapsed, grounding.search_used, detail


def _run_one_verbose(
    api_key: str,
    *,
    model: str,
    query: str,
    key_label: str,
) -> int:
    print(f"\n--- 呼び出し model={model} {key_label} ---")
    print(f"input: {query!r}")

    tool = types.Tool(google_search=types.GoogleSearch())
    cfg = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=512,
        tools=[tool],
    )
    client = genai.Client(api_key=api_key)
    try:
        t0 = time.perf_counter()
        response = client.models.generate_content(
            model=model,
            contents=query,
            config=cfg,
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        for line in _diagnose_gemini_error(e, model=model, purpose="test_grounding"):
            print(line)
        return 1

    text = (getattr(response, "text", None) or "").strip()
    grounding = _parse_grounding_from_response(response)

    print(f"OK ({elapsed:.1f}s)")
    _log_response_usage(response, purpose="test_grounding", key_label=key_label)
    _log_grounding_info(
        grounding,
        purpose="test_grounding",
        key_label=key_label,
        tool_requested=True,
    )
    if text:
        print(f"\n[応答]\n{text}\n")
    else:
        print("警告: 応答テキストが空です。")
        return 2
    return 0


def _status_from_detail(code: int, detail: str) -> str:
    if code == 0:
        return "OK"
    if detail.startswith("404_PROJECT"):
        return "404_PROJECT"
    if detail.startswith("404"):
        return "404"
    if detail.startswith("429"):
        return "429"
    if detail.startswith("EMPTY"):
        return "EMPTY"
    return "ERROR"


def _run_one_key(
    env_suffix: int,
    *,
    model: str,
    query: str,
    verbose: bool = False,
) -> KeyTestResult:
    api_key = _pick_key_by_env_suffix(env_suffix)
    if not api_key:
        return KeyTestResult(
            env_suffix,
            f"GOOGLE_API_KEY_{env_suffix}",
            "SKIP",
            "未設定",
            None,
            False,
        )
    key_label = _key_label_for_suffix(env_suffix, api_key)
    if verbose:
        code = _run_one_verbose(api_key, model=model, query=query, key_label=key_label)
        detail = "verbose" if code == 0 else f"exit={code}"
        return KeyTestResult(
            env_suffix,
            key_label,
            "OK" if code == 0 else "ERROR",
            detail,
            None,
            code == 0,
        )

    code, elapsed, grounding_on, detail = _call_grounding(
        api_key, model=model, query=query
    )
    return KeyTestResult(
        env_suffix,
        key_label,
        _status_from_detail(code, detail),
        detail,
        elapsed,
        grounding_on,
    )


def _print_all_keys_summary(results: list[KeyTestResult], *, model: str) -> int:
    w_suffix = max(4, len(str(max((r.env_suffix for r in results), default=0))))
    print(f"\n=== 一括サマリー model={model} ({len(results)} キー) ===")
    print(f"{'KEY':>{w_suffix}}  {'STATUS':<12} {'TIME':>6}  {'GS':>2}  DETAIL")
    print("-" * (w_suffix + 12 + 6 + 2 + 50))

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        t = f"{r.elapsed_sec:.1f}s" if r.elapsed_sec is not None else "  -"
        gs = "ON" if r.grounding_on else "-"
        detail = r.detail
        if len(detail) > 70:
            detail = detail[:67] + "…"
        print(f"{r.env_suffix:>{w_suffix}}  {r.status:<12} {t:>6}  {gs:>2}  {detail}")
        print(f"     {r.key_label}")

    ok_n = counts.get("OK", 0)
    print("-" * (w_suffix + 12 + 6 + 2 + 50))
    parts = [f"OK={ok_n}"]
    for st in ("404_PROJECT", "404", "429", "EMPTY", "ERROR", "SKIP"):
        if counts.get(st):
            parts.append(f"{st}={counts[st]}")
    print("集計: " + ", ".join(parts))

    usable = [r.env_suffix for r in results if r.status == "OK"]
    if usable:
        print(f"Grounding 利用可: GOOGLE_API_KEY_{', GOOGLE_API_KEY_'.join(str(s) for s in usable)}")
    skip_404 = [r.env_suffix for r in results if r.status == "404_PROJECT"]
    if skip_404:
        print(f"404(new users) スキップ推奨: GOOGLE_API_KEY_{', GOOGLE_API_KEY_'.join(str(s) for s in skip_404)}")

    return 0 if ok_n > 0 else 1


def _collect_all_keys_results(
    *,
    model: str,
    query: str,
    from_key: int,
    to_key: int,
    delay: float,
    verbose: bool,
    quiet_header: bool = False,
) -> list[KeyTestResult]:
    suffixes = list(range(from_key, to_key + 1))
    results: list[KeyTestResult] = []
    if not quiet_header:
        print(f"\n>>> model={model} (keys {from_key}-{to_key})")
    for i, suffix in enumerate(suffixes):
        if i > 0 and delay > 0:
            if not quiet_header:
                print(f"待機 {delay}s …")
            time.sleep(delay)
        if not verbose and not quiet_header:
            print(f"試行 GOOGLE_API_KEY_{suffix} …", flush=True)
        results.append(
            _run_one_key(suffix, model=model, query=query, verbose=verbose)
        )
    return results


def _print_matrix_summary(
    matrix: dict[str, list[KeyTestResult]],
    *,
    from_key: int,
    to_key: int,
) -> int:
    models = list(matrix.keys())
    labels = [_short_model_label(m) for m in models]
    col_w = max(8, max(len(l) for l in labels) if labels else 8)
    key_w = max(3, len(str(to_key)))

    print(f"\n{'=' * 72}")
    print(f"=== マトリクスサマリー keys {from_key}-{to_key} x {len(models)} models ===")
    header = f"{'KEY':>{key_w}} | " + " | ".join(f"{lb:^{col_w}}" for lb in labels)
    print(header)
    print("-" * len(header))

    total_ok = 0
    total_cells = 0
    model_ok: dict[str, int] = {m: 0 for m in models}

    for suffix in range(from_key, to_key + 1):
        cells: list[str] = []
        for m in models:
            row = next((r for r in matrix[m] if r.env_suffix == suffix), None)
            st = row.status if row else "?"
            if st == "OK":
                cell = "OK"
                total_ok += 1
                model_ok[m] += 1
            elif st == "404_PROJECT":
                cell = "404P"
            elif st == "429":
                cell = "429"
            elif st == "404":
                cell = "404"
            elif st == "SKIP":
                cell = "SKIP"
            elif st == "EMPTY":
                cell = "EMPTY"
            else:
                cell = st[:col_w]
            cells.append(f"{cell:^{col_w}}")
            total_cells += 1
        print(f"{suffix:>{key_w}} | " + " | ".join(cells))

    print("-" * len(header))
    ok_cells = " | ".join(f"{model_ok[m]:^{col_w}}" for m in models)
    print(f"{'OK':>{key_w}} | {ok_cells}")
    print(f"合計 OK: {total_ok}/{total_cells}")

    best = sorted(models, key=lambda m: (-model_ok[m], m))
    if best and model_ok[best[0]] > 0:
        print("モデル別 OK 数:")
        for m in best:
            n = model_ok[m]
            if n:
                keys = [str(r.env_suffix) for r in matrix[m] if r.status == "OK"]
                print(f"  {_short_model_label(m):<{col_w}} {n}/10  keys=[{', '.join(keys)}]")

    return 0 if total_ok > 0 else 1


def _run_model_matrix(
    *,
    models: list[str],
    query: str,
    from_key: int,
    to_key: int,
    delay: float,
    model_delay: float,
    verbose: bool,
    per_model_detail: bool,
) -> int:
    matrix: dict[str, list[KeyTestResult]] = {}
    last_code = 1
    for mi, model in enumerate(models):
        if mi > 0 and model_delay > 0:
            print(f"\n=== モデル切替待機 {model_delay}s ===")
            time.sleep(model_delay)
        results = _collect_all_keys_results(
            model=model,
            query=query,
            from_key=from_key,
            to_key=to_key,
            delay=delay,
            verbose=verbose,
            quiet_header=not per_model_detail,
        )
        matrix[model] = results
        if per_model_detail:
            last_code = _print_all_keys_summary(results, model=model)
        else:
            ok_n = sum(1 for r in results if r.status == "OK")
            print(f"  -> {model}: OK={ok_n}/{len(results)}")
            if ok_n:
                last_code = 0
    return _print_matrix_summary(matrix, from_key=from_key, to_key=to_key)


def _run_all_keys(
    *,
    model: str,
    query: str,
    from_key: int,
    to_key: int,
    delay: float,
    verbose: bool,
) -> int:
    suffixes = list(range(from_key, to_key + 1))
    results: list[KeyTestResult] = []

    for i, suffix in enumerate(suffixes):
        if i > 0 and delay > 0:
            print(f"待機 {delay}s …")
            time.sleep(delay)

        if not verbose:
            print(f"試行 GOOGLE_API_KEY_{suffix} …", flush=True)
        results.append(
            _run_one_key(suffix, model=model, query=query, verbose=verbose)
        )

    return _print_all_keys_summary(results, model=model)


def main() -> int:
    _load_env()
    p = argparse.ArgumentParser(description="Google Search グラウンディング最小テスト")
    p.add_argument(
        "--key",
        type=int,
        default=None,
        metavar="N",
        help="GOOGLE_API_KEY_N を指定（未指定時は m03 ローテーションの次キー）",
    )
    p.add_argument(
        "--all-keys",
        action="store_true",
        help=f"GOOGLE_API_KEY_1..{_ALL_KEYS_MAX} を順に試し一括サマリーを表示",
    )
    p.add_argument(
        "--from-key",
        type=int,
        default=1,
        help="--all-keys 時の開始番号（既定 1）",
    )
    p.add_argument(
        "--to-key",
        type=int,
        default=_ALL_KEYS_MAX,
        help=f"--all-keys 時の終了番号（既定 {_ALL_KEYS_MAX}）",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="--all-keys 時に各キーの詳細ログも出力",
    )
    p.add_argument(
        "--rotate",
        action="store_true",
        help="429 等で失敗したら次のキーへ（--max-keys まで）",
    )
    p.add_argument(
        "--max-keys",
        type=int,
        default=3,
        help="--rotate 時の最大キー試行数（既定 3）",
    )
    p.add_argument("--model", default="", help=f"モデル ID（既定 {_DEFAULT_MODEL}）")
    p.add_argument(
        "--models",
        default="",
        help="複数モデル（カンマ区切り）。2.0,2.5,3.1,3.5 または gemini-... 名。--all-keys と併用",
    )
    p.add_argument(
        "--model-suite",
        action="store_true",
        help="2.0/2.5/3.1/3.5 系の既定6モデルを keys 1-10 で一括テスト（--all-keys 必須）",
    )
    p.add_argument(
        "--model-delay",
        type=float,
        default=5.0,
        help="--models / --model-suite 時のモデル切替待機秒（既定 5）",
    )
    p.add_argument(
        "--per-model-detail",
        action="store_true",
        help="マトリクス実行時も各モデルの詳細サマリーを表示",
    )
    p.add_argument("--query", default=_DEFAULT_QUERY, help="テスト用プロンプト（短い質問推奨）")
    p.add_argument("--list-keys", action="store_true", help="ロード済みキー一覧を表示して終了")
    p.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="キー切替・再試行前の待機秒（--all-keys ではキー間にも適用）",
    )
    args = p.parse_args()

    model = _resolve_model(args.model)

    if args.list_keys:
        _list_loaded_keys()
        return 0

    if args.all_keys:
        if args.key is not None or args.rotate:
            print("警告: --all-keys は --key / --rotate と併用しません。", file=sys.stderr)
        from_k = max(1, args.from_key)
        to_k = max(from_k, args.to_key)

        if args.model_suite:
            models = _default_suite_models()
        elif args.models.strip():
            models = _parse_models_arg(args.models.strip())
        else:
            models = []

        if models:
            print(f"モデル列 ({len(models)}): {', '.join(models)}")
            print(f"プロンプト長: {len(args.query)} 字")
            print(f"対象: GOOGLE_API_KEY_{from_k} .. GOOGLE_API_KEY_{to_k}")
            print(f"キー間 delay={args.delay}s / モデル間 delay={args.model_delay}s")
            return _run_model_matrix(
                models=models,
                query=args.query,
                from_key=from_k,
                to_key=to_k,
                delay=args.delay,
                model_delay=args.model_delay,
                verbose=args.verbose,
                per_model_detail=args.per_model_detail,
            )

        print(f"モデル: {model}")
        print(f"プロンプト長: {len(args.query)} 字")
        print(f"対象: GOOGLE_API_KEY_{from_k} .. GOOGLE_API_KEY_{to_k}")
        return _run_all_keys(
            model=model,
            query=args.query,
            from_key=from_k,
            to_key=to_k,
            delay=args.delay,
            verbose=args.verbose,
        )

    print(f"モデル: {model}")
    print(f"プロンプト長: {len(args.query)} 字")

    attempts = args.max_keys if args.rotate else 1
    last_code = 1

    for attempt in range(attempts):
        if attempt > 0 and args.delay > 0:
            print(f"待機 {args.delay}s …")
            time.sleep(args.delay)

        if args.key is not None and not args.rotate:
            api_key = _pick_key_by_env_suffix(args.key)
            if not api_key:
                print(f"ERROR: GOOGLE_API_KEY_{args.key} が .env にありません。", file=sys.stderr)
                return 1
            key_label = _key_label_for_suffix(args.key, api_key)
        elif args.key is not None and args.rotate:
            suffix = args.key + attempt
            api_key = _pick_key_by_env_suffix(suffix)
            if not api_key:
                print(f"スキップ: GOOGLE_API_KEY_{suffix} なし")
                continue
            key_label = f"GOOGLE_API_KEY_{suffix} (…{api_key[-4:]})"
        else:
            api_key = _pick_key_rotate()
            if not api_key:
                print("ERROR: 利用可能な API キーがありません。", file=sys.stderr)
                return 1
            key_label = api_key_manager.format_key_log(api_key=api_key)

        last_code = _run_one_verbose(api_key, model=model, query=args.query, key_label=key_label)
        if last_code == 0:
            return 0
        if not args.rotate:
            break
        print("→ 次キーで再試行 …")

    return last_code


if __name__ == "__main__":
    raise SystemExit(main())
