import asyncio

from models import ContentType
from services.focus import OFFICIAL_SEARCH_DOMAINS
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_text


class GoogleConnector(PublicWebSearchConnector):
    """Web search via open-source ddgs (multi-backend metasearch)."""

    name = "google"
    site = None
    platform_label = "Google"
    content_type = ContentType.WEBSITE

    async def search(self, query: str) -> list[dict]:
        site_clause = " OR ".join(f"site:{domain}" for domain in OFFICIAL_SEARCH_DOMAINS)
        official_query = f"{query} ({site_clause})"

        official, general = await asyncio.gather(
            ddgs_text(
                official_query,
                source=self.name,
                max_results=8,
                region="xa-ar",
                timeout=8.0,
            ),
            ddgs_text(
                query,
                source=self.name,
                max_results=10,
                region="xa-ar",
                timeout=10.0,
            ),
            return_exceptions=True,
        )
        if isinstance(official, Exception):
            official = []
        if isinstance(general, Exception) or not general:
            general = await ddgs_text(
                query,
                source=self.name,
                max_results=10,
                region="wt-wt",
                timeout=8.0,
            )

        seen: set[str] = set()
        results: list[dict] = []
        for item in list(official or []) + list(general or []):
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            item["source"] = self.name
            results.append(item)
        return results
