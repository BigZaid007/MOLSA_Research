from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import httpx
from bs4 import BeautifulSoup

from models import ContentType, ResearchItem
from services.arabic import normalize_arabic
from services.focus import has_ministry_entity_phrase, is_ministry_topic, title_names_other_ministry
from .base import BaseConnector, DEFAULT_HEADERS
from .ddgs_search import ddgs_news

logger = logging.getLogger(__name__)

_WINDOWS = {"d": 2, "w": 7, "m": 31, "y": 365}


def _recent_enough(published, timelimit: str | None) -> bool:
    if not published or not timelimit:
        return True
    days = _WINDOWS.get((timelimit or "").lower())
    if days is None:
        return True
    from datetime import datetime, timedelta

    return published >= datetime.now() - timedelta(days=days)


def _rss_matches(title: str, summary: str, query: str) -> bool:
    hay = f"{title} {summary}"
    if title_names_other_ministry(title):
        return False
    if is_ministry_topic(query):
        return has_ministry_entity_phrase(hay)
    needle = normalize_arabic(query)
    blob = normalize_arabic(hay)
    if needle and needle in blob:
        return True
    tokens = [t for t in needle.split() if len(t) > 2]
    return bool(tokens) and any(token in blob for token in tokens)

RSS_FEEDS = [
    "https://www.ina.iq/rss.xml",
    "https://www.rudaw.net/arabic/rss.xml",
    "https://almadapaper.net/feed",
    "https://baghdad24.news/feed",
    "https://www.iraqinews.com/feed/",
]


class RSSConnector(BaseConnector):
    name = "rss"
    content_type = ContentType.RSS

    async def search(self, query: str, timelimit: str | None = None) -> list[dict]:
        results: list[dict] = []

        for feed_url in RSS_FEEDS:
            try:
                async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
                    response = await client.get(feed_url, timeout=15)
                    response.raise_for_status()
                    feed = feedparser.parse(response.content)

                for entry in feed.entries[:25]:
                    title = getattr(entry, "title", "") or ""
                    summary = getattr(entry, "summary", "") or ""
                    if not _rss_matches(title, summary, query):
                        continue

                    published = None
                    if getattr(entry, "published", None):
                        try:
                            published = parsedate_to_datetime(entry.published).replace(tzinfo=None)
                        except Exception:
                            published = None
                    if not _recent_enough(published, timelimit):
                        continue

                    results.append(
                        {
                            "title": title,
                            "url": getattr(entry, "link", ""),
                            "snippet": BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)[:220],
                            "source": self.name,
                            "published_date": published,
                            "author": getattr(entry, "author", None),
                            "content_type": ContentType.RSS.value,
                        }
                    )
            except Exception as exc:
                logger.warning("RSS feed failed (%s): %s", feed_url, exc)

        from services.focus import google_news_when_from_timelimit

        # Google News RSS for the query
        try:
            gnews_q = f"{query}{google_news_when_from_timelimit(timelimit)}"
            gnews_url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(gnews_q)}&hl=ar&gl=IQ&ceid=IQ:ar"
            )
            async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
                response = await client.get(gnews_url, timeout=20)
                response.raise_for_status()
                feed = feedparser.parse(response.content)
            for entry in feed.entries[:10]:
                published = None
                if getattr(entry, "published", None):
                    try:
                        published = parsedate_to_datetime(entry.published).replace(tzinfo=None)
                    except Exception:
                        published = None
                results.append(
                    {
                        "title": getattr(entry, "title", "") or "Untitled",
                        "url": getattr(entry, "link", ""),
                        "snippet": BeautifulSoup(
                            getattr(entry, "summary", "") or "", "html.parser"
                        ).get_text(" ", strip=True)[:220],
                        "source": self.name,
                        "published_date": published,
                        "content_type": ContentType.RSS.value,
                    }
                )
        except Exception as exc:
            logger.warning("Google News RSS fallback failed: %s", exc)

        if len(results) < 3:
            extra = await ddgs_news(
                query,
                source=self.name,
                max_results=8,
                region="xa-ar",
                timelimit=timelimit,
            )
            results.extend(extra)

        seen: set[str] = set()
        unique: list[dict] = []
        for item in results:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            item["source"] = self.name
            unique.append(item)
        return unique

    async def fetch(self, item: dict) -> ResearchItem:
        return self.to_item(
            {
                **item,
                "content": item.get("snippet") or item.get("title", ""),
                "content_type": self.content_type.value,
            }
        )

    async def is_available(self) -> bool:
        return True
