import asyncio

from models import ContentType
from services.focus import OFFICIAL_SEARCH_DOMAINS
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_news, ddgs_text


class NewsConnector(PublicWebSearchConnector):
    name = "news"
    site = None
    platform_label = "News"
    content_type = ContentType.NEWS

    async def search(self, query: str) -> list[dict]:
        site_clause = " OR ".join(f"site:{domain}" for domain in OFFICIAL_SEARCH_DOMAINS)
        official_task = ddgs_text(
            f"{query} ({site_clause})",
            source=self.name,
            max_results=6,
            region="xa-ar",
            timeout=8.0,
        )
        news_task = self._google_news_search(query, limit=10)
        official, news = await asyncio.gather(official_task, news_task, return_exceptions=True)
        if isinstance(official, Exception):
            official = []
        if isinstance(news, Exception):
            news = []

        results: list[dict] = []
        seen: set[str] = set()
        for item in list(official or []) + list(news or []):
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            item["source"] = self.name
            item["content_type"] = ContentType.NEWS.value
            results.append(item)

        if len(results) < 5:
            extra = await ddgs_news(
                query,
                source=self.name,
                max_results=10,
                region="xa-ar",
                timelimit="m",
            )
            for item in extra:
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                item["source"] = self.name
                item["content_type"] = ContentType.NEWS.value
                results.append(item)
        return results[:14]
