"""Thin async wrapper around the open-source `ddgs` metasearch library."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

BACKEND = "auto"
DEFAULT_TIMEOUT = 8.0

_QUERY_CACHE: dict[str, tuple[list[dict], float]] = {}
_CACHE_TTL = 3600
_MAX_CACHE_SIZE = 500


def _run_text_search(
    query: str,
    max_results: int = 10,
    region: str = "xa-ar",
    timelimit: str | None = None,
    backend: str = BACKEND,
) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        raw = ddgs.text(
            query,
            region=region,
            safesearch="moderate",
            timelimit=timelimit,
            backend=backend,
            max_results=max_results,
        )
    return list(raw or [])


def _run_news_search(
    query: str,
    max_results: int = 10,
    region: str = "xa-ar",
    timelimit: str | None = None,
    backend: str = BACKEND,
) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        raw = ddgs.news(
            query,
            region=region,
            safesearch="moderate",
            timelimit=timelimit,
            backend=backend,
            max_results=max_results,
        )
    return list(raw or [])


def _normalize_text_hit(hit: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "title": hit.get("title") or "Untitled",
        "url": hit.get("href") or hit.get("url") or "",
        "snippet": hit.get("body") or hit.get("description") or "",
        "source": source,
    }


def _normalize_news_hit(hit: dict[str, Any], source: str) -> dict[str, Any]:
    published = None
    date_raw = hit.get("date")
    if date_raw:
        try:
            published = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except Exception:
            published = None
    return {
        "title": hit.get("title") or "Untitled",
        "url": hit.get("url") or hit.get("href") or "",
        "snippet": hit.get("body") or "",
        "source": source,
        "published_date": published,
        "image": hit.get("image"),
    }


def _cache_key(source: str, query: str, max_results: int, region: str) -> str:
    return f"{source}:{query}:{max_results}:{region}"


def _get_cached(key: str) -> list[dict[str, Any]] | None:
    if key in _QUERY_CACHE:
        results, timestamp = _QUERY_CACHE[key]
        if time.time() - timestamp < _CACHE_TTL:
            return results
        del _QUERY_CACHE[key]
    return None


def _set_cache(key: str, results: list[dict[str, Any]]) -> None:
    if len(_QUERY_CACHE) >= _MAX_CACHE_SIZE:
        oldest = min(_QUERY_CACHE.keys(), key=lambda k: _QUERY_CACHE[k][1])
        del _QUERY_CACHE[oldest]
    _QUERY_CACHE[key] = (results, time.time())


async def ddgs_text(
    query: str,
    *,
    source: str = "web",
    max_results: int = 10,
    region: str = "xa-ar",
    timelimit: str | None = None,
    backend: str = BACKEND,
    allowed_domains: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Search the public web via ddgs (Brave backend)."""
    try:
        hits = await asyncio.wait_for(
            asyncio.to_thread(
                partial(
                    _run_text_search,
                    query,
                    max_results=max_results,
                    region=region,
                    timelimit=timelimit,
                    backend=backend,
                )
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("ddgs text search failed for %r: %s", query, exc)
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        item = _normalize_text_hit(hit, source)
        url = item["url"]
        if not url or url in seen:
            continue
        if allowed_domains and not any(d in url.lower() for d in allowed_domains):
            continue
        seen.add(url)
        results.append(item)
    return results


async def ddgs_news(
    query: str,
    *,
    source: str = "news",
    max_results: int = 10,
    region: str = "xa-ar",
    timelimit: str | None = None,
    backend: str = BACKEND,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Search news via ddgs."""
    try:
        hits = await asyncio.wait_for(
            asyncio.to_thread(
                partial(
                    _run_news_search,
                    query,
                    max_results=max_results,
                    region=region,
                    timelimit=timelimit,
                    backend=backend,
                )
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("ddgs news search failed for %r: %s", query, exc)
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        item = _normalize_news_hit(hit, source)
        url = item["url"]
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(item)
    return results