"""Article extraction adapted from Trafilatura, news-please (JSON-LD), Readability, and Newspaper4k."""

from __future__ import annotations

import json
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
    result = _merge(result, _extract_jsonld(html))
    result = _merge(result, _extract_opengraph(html))
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
        if not (text or "").strip():
            text = trafilatura.extract(
                html,
                url=url or None,
                include_comments=False,
                favor_recall=True,
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


def _walk_jsonld(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_walk_jsonld(item))
        return found
    if not isinstance(node, dict):
        return found
    types = node.get("@type")
    labels = types if isinstance(types, list) else [types]
    labels = [str(label or "").lower() for label in labels]
    if any(label in {"newsarticle", "article", "reportage", "blogposting"} for label in labels):
        found.append(node)
    if "@graph" in node:
        found.extend(_walk_jsonld(node.get("@graph")))
    return found


def _jsonld_author(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list) and value:
        return _jsonld_author(value[0])
    return ""


def _extract_jsonld(html: str) -> dict[str, Any]:
    """news-please style NewsArticle JSON-LD."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
            raw = script.string or script.get_text() or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for node in _walk_jsonld(data):
                body = node.get("articleBody") or node.get("description") or ""
                title = node.get("headline") or node.get("name") or ""
                image = node.get("image")
                if isinstance(image, dict):
                    image = image.get("url")
                elif isinstance(image, list) and image:
                    image = image[0].get("url") if isinstance(image[0], dict) else image[0]
                return {
                    "title": str(title or "").strip(),
                    "content": " ".join(str(body).split()),
                    "meta": {
                        "author": _jsonld_author(node.get("author")),
                        "date": node.get("datePublished") or node.get("dateCreated"),
                        "image": image,
                    },
                }
    except Exception as exc:
        logger.debug("JSON-LD extract failed: %s", exc)
    return {}


def _extract_opengraph(html: str) -> dict[str, Any]:
    try:
        soup = BeautifulSoup(html, "html.parser")

        def prop(name: str) -> str:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            return (tag.get("content") or "").strip() if tag else ""

        title = prop("og:title") or prop("twitter:title")
        description = prop("og:description") or prop("twitter:description")
        return {
            "title": title,
            "content": description,
            "meta": {
                "date": prop("article:published_time") or prop("og:updated_time"),
                "image": prop("og:image"),
                "sitename": prop("og:site_name"),
            },
        }
    except Exception as exc:
        logger.debug("OpenGraph extract failed: %s", exc)
        return {}


def _html_title(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
    except Exception:
        pass
    return ""
