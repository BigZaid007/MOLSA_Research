from models import ContentType
from .social import SocialConnector, classify_social_url, extract_hashtags, extract_mentions


class XConnector(SocialConnector):
    name = "x"
    site = "x.com"
    platform_label = "X"
    content_type = ContentType.SOCIAL
    allowed_domains = ["x.com", "twitter.com"]
    post_url_hints = ["/status/"]
    query_templates = [
        'site:x.com inurl:status "{q}"',
        'site:twitter.com inurl:status "{q}"',
        'site:x.com "{q}"',
        'site:twitter.com "وزارة العمل" OR "وزير العمل"',
        'site:x.com #وزارة_العمل',
    ]

    async def fetch(self, item: dict):
        """Skip full page fetch for X social posts — use snippet only."""
        from .base import BaseConnector
        url = item.get("url", "")
        title = item.get("title", "Untitled")
        snippet = item.get("snippet", "")
        meta = item.get("metadata") or {}
        research_item = BaseConnector.to_item(
            self,
            {
                **item,
                "title": title,
                "url": url,
                "content": snippet or title,
                "content_type": self.content_type.value,
                "status": "partial",
                "metadata": {**(item.get("metadata") or {}), "fetch_mode": "snippet"},
            },
        )
        research_item.metadata.update(meta)
        return research_item
        results = await super().search(query)
        for item in results:
            item["source"] = self.name
            meta = item.setdefault("metadata", {})
            meta["platform"] = "X"
            url = item.get("url") or ""
            meta["post_kind"] = classify_social_url(url, "x")
            text = f"{item.get('title', '')} {item.get('snippet', '')}"
            meta["hashtags"] = extract_hashtags(text)
            meta["mentions"] = extract_mentions(text)
        return results
