from models import ContentType
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_text


class BingConnector(PublicWebSearchConnector):
    name = "bing"
    site = None
    platform_label = "Bing"
    content_type = ContentType.WEBSITE

    async def search(self, query: str) -> list[dict]:
        results = await ddgs_text(
            query,
            source=self.name,
            max_results=10,
            region="xa-ar",
            backend="bing",
            timeout=12.0,
        )
        if not results:
            results = await ddgs_text(
                query,
                source=self.name,
                max_results=10,
                region="wt-wt",
                timeout=12.0,
            )
        for item in results:
            item["source"] = self.name
        return results
