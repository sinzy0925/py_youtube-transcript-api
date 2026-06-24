#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静的サイト生成: output/ の summary.txt → docs/index.html + docs/contents/<video_id>.html

単体:
    python build_html_site.py
    python build_html_site.py --archive-dir output/20260624_172226_AwQYphhy

パイプライン（a05 --build-html / BUILD_HTML_SITE=1）からも呼べる。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from a04_send_result_email import _sanitize_nbsp_and_ws, _summary_markdown_to_html_fragment

PYTHON = os.path.basename(__file__)

_CONTENT_PAGE_STYLE = """
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.55;
  color: #202124;
  font-size: 15px;
  max-width: 720px;
  margin: 0 auto;
  padding: 1rem 1.25rem 2rem;
}
a { color: #1a73e8; }
nav { margin-bottom: 1.25rem; font-size: 0.95rem; }
h1 { font-size: 1.35rem; line-height: 1.4; margin: 0 0 0.5rem; }
.meta { color: #5f6368; font-size: 0.9rem; margin-bottom: 1.5rem; }
article h2, article h3 { margin-top: 1.25rem; }
article pre {
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 14px;
  background: #f8f9fa;
  padding: 0.75rem;
  border-radius: 4px;
  overflow-x: auto;
}
""".strip()

_INDEX_PAGE_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", sans-serif;
  line-height: 1.5;
  color: #202124;
  font-size: 15px;
  max-width: 880px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 2.5rem;
  background: #eef1f4;
}
a { color: inherit; text-decoration: none; }
.index-header {
  margin-bottom: 1.25rem;
  padding: 1.1rem 1.25rem;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.12);
}
.index-header h1 {
  font-size: 1.45rem;
  line-height: 1.35;
  margin: 0 0 0.35rem;
  letter-spacing: -0.01em;
}
.index-header p {
  margin: 0;
  color: #5f6368;
  font-size: 0.9rem;
}
.index-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.index-item {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.1);
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}
.index-item:hover {
  box-shadow: 0 4px 12px rgba(60, 64, 67, 0.14);
  transform: translateY(-1px);
}
.index-item-link {
  display: grid;
  grid-template-columns: 5.6rem 1fr;
  gap: 0.75rem 1rem;
  align-items: start;
  padding: 0.85rem 1rem;
}
.index-item-main {
  min-width: 0;
}
.index-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-bottom: 0.4rem;
}
.index-tag {
  display: inline-block;
  font-size: 0.7rem;
  line-height: 1.2;
  padding: 0.18rem 0.5rem;
  border-radius: 999px;
  font-weight: 600;
  letter-spacing: 0.01em;
  background: #e8eaed;
  color: #3c4043;
}
.index-tag[data-cat="投資"] { background: #e8f0fe; color: #1967d2; }
.index-tag[data-cat="不動産"] { background: #e6f4ea; color: #137333; }
.index-tag[data-cat="年金"] { background: #fce8e6; color: #c5221f; }
.index-tag[data-cat="税制"] { background: #fef7e0; color: #b06000; }
.index-tag[data-cat="AI"] { background: #f3e8fd; color: #7b1fa2; }
.index-tag[data-cat="学習"] { background: #e0f7fa; color: #00695c; }
.index-tag[data-cat="ライフハック"] { background: #fff3e0; color: #e65100; }
.index-tag[data-cat="社会・時事"] { background: #f1f3f4; color: #5f6368; }
.index-item-date {
  display: block;
  font-size: 0.78rem;
  line-height: 1.35;
  color: #5f6368;
  font-variant-numeric: tabular-nums;
  padding-top: 0.15rem;
  border-right: 1px solid #e8eaed;
  padding-right: 0.75rem;
}
.index-item-date .time {
  display: block;
  margin-top: 0.15rem;
  color: #80868b;
  font-size: 0.72rem;
}
.index-item-title {
  display: block;
  color: #1a73e8;
  font-size: 0.97rem;
  line-height: 1.55;
  font-weight: 500;
}
.index-item:hover .index-item-title {
  text-decoration: underline;
  text-underline-offset: 2px;
}
.index-empty {
  padding: 2rem 1rem;
  text-align: center;
  color: #5f6368;
  background: #fff;
  border-radius: 10px;
}
@media (max-width: 520px) {
  body { padding: 1rem 0.75rem 2rem; }
  .index-item-link {
    grid-template-columns: 1fr;
    gap: 0.35rem;
  }
  .index-item-date {
    border-right: none;
    padding-right: 0;
    padding-top: 0;
    font-size: 0.75rem;
  }
  .index-item-date .time {
    display: inline;
    margin-top: 0;
    margin-left: 0.35rem;
  }
}
""".strip()


@dataclass(frozen=True)
class CategoryConfig:
    max_tags: int
    summary_preview_chars: int
    categories: dict[str, list[str]]


@dataclass(frozen=True)
class ArchiveEntry:
    archive_dir: Path
    video_id: str
    title: str
    watch_url: str
    sort_key: str
    summary_path: Path


def _script_root() -> Path:
    return Path(__file__).resolve().parent


def _load_category_config(path: Optional[Path] = None) -> CategoryConfig:
    cfg_path = path or (_script_root() / "categories.yaml")
    max_tags = 2
    summary_preview_chars = 500
    categories: dict[str, list[str]] = {}

    if not cfg_path.is_file():
        return CategoryConfig(max_tags, summary_preview_chars, categories)

    try:
        import yaml
    except ImportError:
        print(
            f"警告: PyYAML がありません。pip install PyYAML でカテゴリタグを有効化できます。 : ({PYTHON})",
            file=sys.stderr,
        )
        return CategoryConfig(max_tags, summary_preview_chars, categories)

    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        print(f"警告: categories.yaml の読み込みに失敗: {e} : ({PYTHON})", file=sys.stderr)
        return CategoryConfig(max_tags, summary_preview_chars, categories)

    if not isinstance(raw, dict):
        return CategoryConfig(max_tags, summary_preview_chars, categories)

    if isinstance(raw.get("max_tags"), int) and raw["max_tags"] > 0:
        max_tags = raw["max_tags"]
    if isinstance(raw.get("summary_preview_chars"), int) and raw["summary_preview_chars"] > 0:
        summary_preview_chars = raw["summary_preview_chars"]

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

    return CategoryConfig(max_tags, summary_preview_chars, categories)


def _classification_text(entry: ArchiveEntry, preview_chars: int) -> str:
    parts = [entry.title]
    try:
        text = entry.summary_path.read_text(encoding="utf-8")
        _title, _url, body = _parse_summary_header(text)
        if not body.strip():
            body = text
        parts.append(body[:preview_chars])
    except OSError:
        pass
    return _sanitize_nbsp_and_ws("\n".join(parts))


def _classify_tags(text: str, config: CategoryConfig) -> list[str]:
    if not text.strip() or not config.categories:
        return []

    scores: dict[str, int] = {}
    lower = text.casefold()
    for cat, keywords in config.categories.items():
        score = 0
        for kw in keywords:
            if not kw:
                continue
            kw_cf = kw.casefold()
            count = lower.count(kw_cf)
            if count:
                score += count * (3 if len(kw) >= 4 else 2)
        if score > 0:
            scores[cat] = score

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [cat for cat, _ in ranked[: config.max_tags]]


def _render_index_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    pills = "".join(
        f'<span class="index-tag" data-cat="{html.escape(tag)}">{html.escape(tag)}</span>'
        for tag in tags
    )
    return f'<div class="index-tags">{pills}</div>'


def _video_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _parse_summary_header(text: str) -> tuple[str, str, str]:
    """summary.txt 先頭の タイトル／URL 行を抜き、本文を返す。"""
    title = ""
    url = ""
    body_lines: list[str] = []
    phase = "header"
    for line in text.splitlines():
        s = line.strip()
        if phase == "header":
            if s.startswith("タイトル："):
                title = s[len("タイトル：") :].strip()
                continue
            if s.startswith("URL："):
                url = s[len("URL：") :].strip()
                continue
            if not s and not title and not url:
                continue
            phase = "body"
        if phase == "body":
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return title, url, body


def _load_video_info(archive_dir: Path) -> dict:
    path = archive_dir / "video_info.json"
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sort_key_from_dir_name(name: str) -> str:
    m = re.match(r"^(\d{8}_\d{6})", name)
    if m:
        return m.group(1)
    return name


def _entry_from_archive_dir(archive_dir: Path) -> Optional[ArchiveEntry]:
    summary_path = archive_dir / "summary.txt"
    if not summary_path.is_file():
        return None

    info = _load_video_info(archive_dir)
    try:
        summary_text = summary_path.read_text(encoding="utf-8")
    except OSError:
        return None

    title_from_summary, url_from_summary, body = _parse_summary_header(summary_text)
    if not body.strip():
        body = summary_text.strip()

    video_id = (info.get("video_id") or "").strip()
    if not video_id:
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url_from_summary)
        if m:
            video_id = m.group(1)
    if not video_id:
        return None

    title = _sanitize_nbsp_and_ws(
        (info.get("title") or title_from_summary or "（タイトル不明）").strip()
    )
    watch_url = (url_from_summary or _video_watch_url(video_id)).strip()
    fetched = (info.get("fetched_utc") or "").strip()
    sort_key = fetched or _sort_key_from_dir_name(archive_dir.name)

    return ArchiveEntry(
        archive_dir=archive_dir,
        video_id=video_id,
        title=title,
        watch_url=watch_url,
        sort_key=sort_key,
        summary_path=summary_path,
    )


def discover_archives(output_root: Path) -> list[ArchiveEntry]:
    """output_root 配下の成果物を列挙し、video_id ごとに最新だけ残す。"""
    if not output_root.is_dir():
        return []

    by_id: dict[str, ArchiveEntry] = {}
    for child in sorted(output_root.iterdir()):
        if not child.is_dir():
            continue
        entry = _entry_from_archive_dir(child)
        if entry is None:
            continue
        prev = by_id.get(entry.video_id)
        if prev is None or entry.sort_key >= prev.sort_key:
            by_id[entry.video_id] = entry

    entries = list(by_id.values())
    entries.sort(key=lambda e: e.sort_key, reverse=True)
    return entries


def _summary_body_html(summary_path: Path) -> str:
    text = summary_path.read_text(encoding="utf-8")
    _title, _url, body = _parse_summary_header(text)
    if not body.strip():
        body = text.strip()
    body = _sanitize_nbsp_and_ws(body)
    return _summary_markdown_to_html_fragment(body)


def _write_content_page(entry: ArchiveEntry, contents_dir: Path) -> Path:
    contents_dir.mkdir(parents=True, exist_ok=True)
    out_path = contents_dir / f"{entry.video_id}.html"
    body_html = _summary_body_html(entry.summary_path)
    title_esc = html.escape(entry.title)
    url_esc = html.escape(entry.watch_url, quote=True)
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_esc}</title>
  <style>{_CONTENT_PAGE_STYLE}</style>
</head>
<body>
  <nav><a href="../index.html">一覧へ</a></nav>
  <h1>{title_esc}</h1>
  <p class="meta"><a href="{url_esc}" rel="noopener noreferrer">YouTube で見る</a></p>
  <article>
{body_html}
  </article>
</body>
</html>
"""
    out_path.write_text(page, encoding="utf-8")
    return out_path


def _parse_sort_datetime(sort_key: str) -> Optional[datetime]:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$", sort_key)
    if m:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    if "T" in sort_key:
        try:
            return datetime.fromisoformat(sort_key.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def _format_index_date_parts(sort_key: str) -> tuple[str, str, str]:
    """一覧用 (ISO日付, 時刻, datetime属性) を返す。"""
    dt = _parse_sort_datetime(sort_key)
    if dt is None:
        return "", "", ""
    return (
        dt.strftime("%Y-%m-%d"),
        dt.strftime("%H:%M"),
        dt.strftime("%Y-%m-%dT%H:%M"),
    )


def _write_index(
    entries: list[ArchiveEntry],
    html_dir: Path,
    *,
    category_config: Optional[CategoryConfig] = None,
) -> Path:
    html_dir.mkdir(parents=True, exist_ok=True)
    out_path = html_dir / "index.html"
    cat_cfg = category_config or _load_category_config()
    items: list[str] = []
    for entry in entries:
        title_esc = html.escape(entry.title)
        href = html.escape(f"contents/{entry.video_id}.html", quote=True)
        tags = _classify_tags(_classification_text(entry, cat_cfg.summary_preview_chars), cat_cfg)
        tags_html = _render_index_tags(tags)
        day, clock, dt_attr = _format_index_date_parts(entry.sort_key)
        if day:
            date_html = (
                f'<time class="index-item-date" datetime="{html.escape(dt_attr)}">'
                f"{html.escape(day)}"
                f'<span class="time">{html.escape(clock)}</span>'
                f"</time>"
            )
        else:
            date_html = '<span class="index-item-date">—</span>'
        items.append(
            f"""    <li class="index-item">
      <a class="index-item-link" href="{href}">
        {date_html}
        <div class="index-item-main">
          {tags_html}
          <span class="index-item-title">{title_esc}</span>
        </div>
      </a>
    </li>"""
        )

    count = len(entries)
    count_label = f"{count} 件の要約"
    list_html = (
        "\n".join(items)
        if items
        else '  <p class="index-empty">まだ要約がありません</p>'
    )
    list_block = (
        f"  <ul class=\"index-list\">\n{list_html}\n  </ul>" if items else list_html
    )
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YouTube 要約一覧</title>
  <style>{_INDEX_PAGE_STYLE}</style>
</head>
<body>
  <header class="index-header">
    <h1>YouTube 要約一覧</h1>
    <p>{html.escape(count_label)}</p>
  </header>
{list_block}
</body>
</html>
"""
    out_path.write_text(page, encoding="utf-8")
    return out_path


def build_html_site(
    output_root: str | Path = "output",
    html_dir: str | Path = "docs",
    *,
    archive_dirs: Optional[list[str | Path]] = None,
    categories_file: Optional[str | Path] = None,
) -> dict[str, int | str]:
    """
    output/ を走査して docs/（既定）を生成する。
    archive_dirs を渡した場合はそのディレクトリも含めて再スキャン（単体追記用）。
    """
    output_root = Path(output_root)
    html_dir = Path(html_dir)
    contents_dir = html_dir / "contents"
    cat_cfg = _load_category_config(Path(categories_file) if categories_file else None)

    entries = discover_archives(output_root)
    if archive_dirs:
        seen = {e.video_id for e in entries}
        for ad in archive_dirs:
            entry = _entry_from_archive_dir(Path(ad))
            if entry is None:
                continue
            prev = next((e for e in entries if e.video_id == entry.video_id), None)
            if prev is None:
                entries.append(entry)
            elif entry.sort_key >= prev.sort_key:
                entries.remove(prev)
                entries.append(entry)
            seen.add(entry.video_id)
        entries.sort(key=lambda e: e.sort_key, reverse=True)

    written = 0
    for entry in entries:
        _write_content_page(entry, contents_dir)
        written += 1

    index_path = _write_index(entries, html_dir, category_config=cat_cfg)
    return {
        "entries": len(entries),
        "pages_written": written,
        "index_path": str(index_path),
        "html_dir": str(html_dir.resolve()),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="output/ の要約から docs/ 静的サイトを生成")
    p.add_argument(
        "--output-root",
        default="output",
        help="成果物の親ディレクトリ（既定: output）",
    )
    p.add_argument(
        "--html-dir",
        default="docs",
        help="生成先（既定: docs。GitHub Pages の /docs 公開用）",
    )
    p.add_argument(
        "--archive-dir",
        action="append",
        default=[],
        dest="archive_dirs",
        metavar="DIR",
        help="追加で含める成果物ディレクトリ（複数可）",
    )
    p.add_argument(
        "--categories-file",
        default="",
        help="カテゴリ定義 YAML（既定: リポジトリ直下 categories.yaml）",
    )
    args = p.parse_args()

    result = build_html_site(
        args.output_root,
        args.html_dir,
        archive_dirs=args.archive_dirs or None,
        categories_file=args.categories_file or None,
    )
    print(
        f"HTML サイト生成完了: {result['pages_written']} 件 → {result['html_dir']} "
        f"（index: {result['index_path']}） : ({PYTHON})"
    )


if __name__ == "__main__":
    main()
