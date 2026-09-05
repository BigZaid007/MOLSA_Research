"""Article extraction adapted from Trafilatura, Readability, and Newspaper4k."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MIN_BODY_CHARS = 400


def make_excerpt(text: str, sentences: int = 4, max_chars: int = 520) -> str:
    """First 3–4 sentences of an extracted article body."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    parts = [p.strip() for p in re.split(r"(?<=[.!?؟。])\s+", cleaned) if p.strip()]
    excerpt = " ".join(parts[:sentences]) if parts else cleaned
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return excerpt


def _meta_value(meta: Any, name: str) -> Any:
    if meta is None:
        return None
    if isinstance(meta, dict):
        return meta.get(name)
    return getattr(meta, name, None)


def extract_from_html(html: str, url: str = "") -> dict[str, Any]:
    """Extract title, body, date, and author from HTML. Prefer Trafilatura."""
    if not html or not html.strip():
        return {}

    result = _extract_trafilatura(html, url)
    if _is_rich(result):
        return result

    fallback = _extract_readability(html)
    result = _merge(result, fallback)
    if _is_rich(result):
        return result

    fallback = _extract_newspaper(html, url)
    return _merge(result, fallback)


def _is_rich(result: dict[str, Any]) -> bool:
    return bool((result.get("content") or "").strip())


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if key == "meta":
            meta = dict(merged.get("meta") or {})
            meta.update({k: v for k, v in (value or {}).items() if v})
            merged["meta"] = meta
        elif value and not merged.get(key):
            merged[key] = value
    return merged


def _extract_trafilatura(html: str, url: str) -> dict[str, Any]:
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            include_formatting=False,
            favor_precision=True,
            output_format="txt",
        )
        meta = trafilatura.extract_metadata(html, default_url=url or None)
        title = _meta_value(meta, "title") or _html_title(html)
        author = _meta_value(meta, "author")
        date = _meta_value(meta, "date")
        sitename = _meta_value(meta, "sitename")
        return {
            "title": title or "",
            "content": (text or "").strip(),
            "meta": {
                "author": author,
                "date": date,
                "sitename": sitename,
            },
        }
    except Exception as exc:
        logger.debug("Trafilatura failed for %s: %s", url, exc)
        return {}


def _extract_readability(html: str) -> dict[str, Any]:
    try:
        from readability import Document

        doc = Document(html)
        summary_html = doc.summary() or ""
        soup = BeautifulSoup(summary_html, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        return {
            "title": (doc.title() or "").strip(),
            "content": text,
            "meta": {},
        }
    except Exception as exc:
        logger.debug("Readability failed: %s", exc)
        return {}


def _extract_newspaper(html: str, url: str) -> dict[str, Any]:
    try:
        from newspaper import Article

        article = Article(url or "https://local.invalid")
        article.set_html(html)
        article.parse()
        published = article.publish_date
        if isinstance(published, datetime):
            published = published.isoformat()
        authors = article.authors or []
        return {
            "title": (article.title or "").strip(),
            "content": (article.text or "").strip(),
            "meta": {
                "author": authors[0] if authors else None,
                "date": published,
                "image": article.top_image,
            },
        }
    except Exception as exc:
        logger.debug("Newspaper failed for %s: %s", url, exc)
        return {}


def _html_title(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
    except Exception:
        pass
    return ""
