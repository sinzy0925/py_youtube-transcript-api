#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a02 — カテゴリ判定と参照情報（要約プロンプト注入用）。
    categories.yaml / reference_sources.yaml を読み、キーワードマッチでタグと参照ブロックを返す。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SCRIPT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CategoryConfig:
    max_tags: int
    categories: dict[str, list[str]]


@dataclass(frozen=True)
class ReferenceSource:
    name: str
    url: str


@dataclass(frozen=True)
class ReferenceCategory:
    hints: tuple[str, ...]
    check_items: tuple[str, ...]
    sources: tuple[ReferenceSource, ...]


def _load_yaml(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def load_category_config(path: Optional[Path] = None) -> CategoryConfig:
    cfg_path = path or (_SCRIPT_ROOT / "categories.yaml")
    max_tags = 2
    categories: dict[str, list[str]] = {}
    raw = _load_yaml(cfg_path)
    if not raw:
        return CategoryConfig(max_tags, categories)
    if isinstance(raw.get("max_tags"), int) and raw["max_tags"] > 0:
        max_tags = raw["max_tags"]
    raw_cats = raw.get("categories")
    if isinstance(raw_cats, dict):
        for name, keywords in raw_cats.items():
            cat = str(name).strip()
            if not cat:
                continue
            if isinstance(keywords, list):
                categories[cat] = [str(k).strip() for k in keywords if str(k).strip()]
            elif isinstance(keywords, str) and keywords.strip():
                categories[cat] = [keywords.strip()]
    return CategoryConfig(max_tags, categories)


def classify_categories(
    text: str,
    config: Optional[CategoryConfig] = None,
    *,
    max_tags: Optional[int] = None,
) -> list[str]:
    """タイトル＋文字起こし先頭等を渡し、スコア順にカテゴリ名を返す。"""
    cfg = config or load_category_config()
    limit = max_tags if max_tags is not None else cfg.max_tags
    if not text.strip() or not cfg.categories:
        return []

    scores: dict[str, int] = {}
    lower = text.casefold()
    for cat, keywords in cfg.categories.items():
        score = 0
        for kw in keywords:
            if not kw:
                continue
            kw_cf = kw.casefold()
            count = lower.count(kw_cf)
            if count:
                score += count * max(len(kw_cf), 1)
        if score > 0:
            scores[cat] = score

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [cat for cat, _ in ranked[:limit]]


def load_reference_config(path: Optional[Path] = None) -> dict[str, ReferenceCategory]:
    cfg_path = path or (_SCRIPT_ROOT / "reference_sources.yaml")
    out: dict[str, ReferenceCategory] = {}
    raw = _load_yaml(cfg_path)
    if not raw:
        return out
    raw_cats = raw.get("categories")
    if not isinstance(raw_cats, dict):
        return out
    for name, data in raw_cats.items():
        cat = str(name).strip()
        if not cat or not isinstance(data, dict):
            continue
        hints: list[str] = []
        for h in data.get("hints") or []:
            s = str(h).strip()
            if s:
                hints.append(s)
        check_items: list[str] = []
        for c in data.get("check_items") or []:
            s = str(c).strip()
            if s:
                check_items.append(s)
        sources: list[ReferenceSource] = []
        for src in data.get("sources") or []:
            if isinstance(src, dict):
                n = str(src.get("name") or "").strip()
                u = str(src.get("url") or "").strip()
                if n and u:
                    sources.append(ReferenceSource(n, u))
        out[cat] = ReferenceCategory(
            hints=tuple(hints),
            check_items=tuple(check_items),
            sources=tuple(sources),
        )
    return out


def build_reference_prompt_block(
    category_names: list[str],
    *,
    reference_config: Optional[dict[str, ReferenceCategory]] = None,
) -> str:
    """マッチしたカテゴリの hints / check_items / sources をプロンプト用テキストに。"""
    ref_cfg = reference_config or load_reference_config()
    if not category_names or not ref_cfg:
        return ""

    lines: list[str] = ["【領域別の注意・公式確認先（要約に反映すること）】"]
    seen_urls: set[str] = set()
    for cat in category_names:
        entry = ref_cfg.get(cat)
        if not entry:
            continue
        lines.append(f"\n■ {cat}")
        for h in entry.hints:
            lines.append(f"  - {h}")
        if entry.check_items:
            lines.append("  【要約に含めるチェック項目】" + "、".join(entry.check_items))
        for src in entry.sources:
            if src.url not in seen_urls:
                lines.append(f"  - 公式確認: {src.name} ({src.url})")
                seen_urls.add(src.url)

    if len(lines) <= 1:
        return ""
    lines.append(
        "\n※ 動画内の数字・制度内容は「動画内の説明」として記載し、"
        "最新・個別適用は上記公式サイトで要確認と明記すること。"
    )
    return "\n".join(lines)


def detect_categories_for_summary(
    video_title: str,
    transcript_text: str,
    *,
    preview_chars: int = 3000,
) -> list[str]:
    """要約前: タイトル + 文字起こし先頭でカテゴリ判定。"""
    head = (transcript_text or "")[: max(0, preview_chars)]
    blob = f"{video_title}\n{head}"
    return classify_categories(blob)
