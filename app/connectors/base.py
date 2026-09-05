"""Shared connector helpers for public web research."""

from __future__ import annotations

import asyncio
import logging
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from typing import ClassVar

import feedparser
import httpx
from bs4 import BeautifulSoup

from models import ContentType, ResearchItem
from .ddgs_search import ddgs_news, ddgs_text

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

FETCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
FETCH_LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=20)


class BaseConnector:
    """Base class every source connector implements."""

    name = "base"
    content_type = ContentType.WEBSITE
    _client: ClassVar[httpx.AsyncClient | None] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(
                follow_redirects=True,
                headers=DEFAULT_HEADERS,
                limits=FETCH_LIMITS,
                timeout=FETCH_TIMEOUT,
            )
        return cls._client

    async def search(self, query: str) -> list[dict]:
        raise NotImplementedError

    async def fetch(self, item: dict) -> ResearchItem:
        raise NotImplementedError

    async def is_available(self) -> bool:
        return True

    def log_error(self, message: str, error: Exception | None = None):
        logger.error("Connector %s: %s", self.name, message)
        if error:
            logger.error("Error details: %s", error)

    def to_item(self, data: dict) -> ResearchItem:
        content_type = data.get("content_type", self.content_type)
        if isinstance(content_type, str):
            try:
                content_type = ContentType(content_type)
            except ValueError:
                content_type = self.content_type

        return ResearchItem(
            title=data.get("title") or "Untitled",
            url=data.get("url") or "",
            description=data.get("snippet") or data.get("description"),
            source=data.get("source") or self.name,
            content=data.get("content"),
            content_type=content_type,
            author=data.get("author"),
            published_date=data.get("published_date"),
            keywords=data.get("keywords"),
            image=data.get("image"),
            metadata={"status": data.get("status", "ok"), **(data.get("metadata") or {})},
        )

    async def fetch_batch(self, items: list[dict]) -> list[ResearchItem]:
        """Fetch multiple URLs concurrently with a shared client."""
        client = self.get_client()
        tasks = [self._fetch_one(client, item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed: list[ResearchItem] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Batch fetch error: %s", result)
            elif isinstance(result, ResearchItem):
                processed.append(result)
        return processed

    async def _fetch_one(self, client: httpx.AsyncClient, item: dict) -> ResearchItem:
        url = item.get("url", "")
        title = item.get("title", "Untitled")
        snippet = item.get("snippet", "")
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = " ".join(soup.get_text(" ", strip=True).split())
            content = text[:3000] if text else snippet
        except Exception as exc:
            self.log_error(f"Could not fetch {url}", exc)
            return self.to_item(
                {
                    **item,
                    "content": snippet or title,
                    "content_type": self.content_type.value,
                    "status": "partial",
                    "metadata": {**(item.get("metadata") or {}), "fetch_error": str(exc)},
                }
            )
        return self.to_item(
            {
                **item,
                "title": title,
                "url": url,
                "content": content,
                "content_type": self.content_type.value,
            }
        )


class PublicWebSearchConnector(BaseConnector):
    """
    Search publicly indexed pages via the open-source `ddgs` metasearch library,
    with Google News RSS as a news fallback.
    """

    site: str | None = None
    platform_label: str = "web"
    allowed_domains: list[str] = []

    async def search(self, query: str) -> list[dict]:
        search_query = f"site:{self.site} {query}" if self.site else query
        domains = self._domains()
        results = await ddgs_text(
            search_query,
            source=self.name,
            max_results=10,
            allowed_domains=domains or None,
            region="xa-ar",
            backend="auto",
            timeout=8.0,
        )
        if not results:
            results = await ddgs_text(
                search_query,
                source=self.name,
                max_results=10,
                allowed_domains=domains or None,
                region="xa-ar",
                backend="auto",
                timeout=8.0,
            )
        if not results and not self.site:
            results = await self._google_news_search(search_query)
        for item in results:
            item["source"] = self.name
        return results

    async def fetch(self, item: dict) -> ResearchItem:
        url = item.get("url", "")
        title = item.get("title", "Untitled")
        snippet = item.get("snippet", "")
        try:
            client = self.get_client()
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = " ".join(soup.get_text(" ", strip=True).split())
            content = text[:3000] if text else snippet
        except Exception as exc:
            self.log_error(f"Could not fetch {url}", exc)
            return self.to_item(
                {
                    **item,
                    "content": snippet or title,
                    "content_type": self.content_type.value,
                    "status": "partial",
                    "metadata": {**(item.get("metadata") or {}), "fetch_error": str(exc)},
                }
            )
        return self.to_item(
            {
                **item,
                "title": title,
                "url": url,
                "content": content,
                "content_type": self.content_type.value,
            }
        )

    async def is_available(self) -> bool:
        return True

    def _domains(self) -> list[str]:
        domains: list[str] = []
        if self.site:
            domains.append(self.site)
        domains.extend(self.allowed_domains or [])
        return list(dict.fromkeys(domains))

    async def _ddgs_search(
        self,
        query: str,
        limit: int = 10,
        *,
        allowed_domains: list[str] | None = None,
        timelimit: str | None = None,
    ) -> list[dict]:
        domains = allowed_domains if allowed_domains is not None else (self._domains() or None)
        return await ddgs_text(
            query,
            source=self.name,
            max_results=limit,
            allowed_domains=domains,
            timelimit=timelimit,
            region="xa-ar",
            backend="auto",
            timeout=8.0,
        )

    async def _google_news_search(self, query: str, limit: int = 10) -> list[dict]:
        """Reliable keyless news/web result source (Arabic Iraq + English)."""
        results: list[dict] = []
        locales = [
            ("ar", "IQ", "IQ:ar"),
            ("en-US", "US", "US:en"),
        ]
        seen_urls: set[str] = set()
        client = self.get_client()

        for hl, gl, ceid in locales:
            try:
                url = (
                    "https://news.google.com/rss/search?"
                    f"q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
                )
                response = await client.get(
                    url,
                    timeout=15.0,
                    headers={**DEFAULT_HEADERS, "Referer": "https://news.google.com/"},
                )
                response.raise_for_status()
                feed = feedparser.parse(response.content)

                for entry in feed.entries[:limit]:
                    link = getattr(entry, "link", "") or ""
                    if not link or link in seen_urls:
                        continue
                    seen_urls.add(link)
                    published = None
                    if getattr(entry, "published", None):
                        try:
                            published = parsedate_to_datetime(entry.published).replace(tzinfo=None)
                        except Exception:
                            published = None
                    results.append(
                        {
                            "title": getattr(entry, "title", "") or "Untitled",
                            "url": link,
                            "snippet": BeautifulSoup(
                                getattr(entry, "summary", "") or "", "html.parser"
                            ).get_text(" ", strip=True)[:220],
                            "source": self.name,
                            "published_date": published,
                        }
                    )
                    if len(results) >= limit:
                        return results
            except Exception as exc:
                self.log_error(f"Google News RSS search failed ({hl})", exc)

        if not results:
            results = await ddgs_news(query, source=self.name, max_results=limit, region="xa-ar")
        return results