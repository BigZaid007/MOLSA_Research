from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import httpx
from bs4 import BeautifulSoup

from models import ContentType, ResearchItem
from .base import BaseConnector, DEFAULT_HEADERS
from .ddgs_search import ddgs_news

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://www.ina.iq/rss.xml",
    "https://www.rudaw.net/arabic/rss.xml",
]


class RSSConnector(BaseConnector):
    name = "rss"
    content_type = ContentType.RSS

    async def search(self, query: str) -> list[dict]:
        results: list[dict] = []
        query_lower = query.lower()
        tokens = [t for t in query_lower.replace("-", " ").split() if len(t) > 1]

        for feed_url in RSS_FEEDS:
            try:
                async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
                    response = await client.get(feed_url, timeout=15)
                    response.raise_for_status()
                    feed = feedparser.parse(response.content)

                for entry in feed.entries[:25]:
                    title = getattr(entry, "title", "") or ""
                    summary = getattr(entry, "summary", "") or ""
                    haystack = f"{title} {summary}".lower()
                    if query_lower not in haystack and not any(t in haystack for t in tokens):
                        continue

                    published = None
                    if getattr(entry, "published", None):
                        try:
                            published = parsedate_to_datetime(entry.published).replace(tzinfo=None)
                        except Exception:
                            published = None

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

        # Google News RSS for the query
        try:
            gnews_url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(query)}&hl=ar&gl=IQ&ceid=IQ:ar"
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
            extra = await ddgs_news(query, source=self.name, max_results=8, region="xa-ar")
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
