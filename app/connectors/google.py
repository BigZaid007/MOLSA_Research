import asyncio

from models import ContentType
from services.focus import OFFICIAL_SEARCH_DOMAINS
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_text


class GoogleConnector(PublicWebSearchConnector):
    """Web + news search via ddgs metasearch and Google News RSS."""

    name = "google"
    site = None
    platform_label = "Google"
    content_type = ContentType.WEBSITE

    async def search(self, query: str, timelimit: str | None = None) -> list[dict]:
        site_clause = " OR ".join(
            f"site:{domain}" for domain in OFFICIAL_SEARCH_DOMAINS[:4]
        )
        official_query = f"{query} ({site_clause})"

        official, general, news = await asyncio.gather(
            ddgs_text(
                official_query,
                source=self.name,
                max_results=8,
                region="xa-ar",
                timelimit=timelimit,
                timeout=8.0,
            ),
            ddgs_text(
                query,
                source=self.name,
                max_results=10,
                region="xa-ar",
                timelimit=timelimit,
                timeout=10.0,
            ),
            self._google_news_search(query, limit=10, timelimit=timelimit),
            return_exceptions=True,
        )
        if isinstance(official, Exception):
            official = []
        if isinstance(general, Exception):
            general = []
        if isinstance(news, Exception):
            news = []
        if not general:
            general = await ddgs_text(
                query,
                source=self.name,
                max_results=10,
                region="wt-wt",
                timelimit=timelimit,
                timeout=8.0,
            )

        seen: set[str] = set()
        results: list[dict] = []
        for item in list(news or []) + list(official or []) + list(general or []):
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            item["source"] = self.name
            results.append(item)
        return results
