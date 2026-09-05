from models import ContentType
from .social import SocialConnector


class InstagramConnector(SocialConnector):
    name = "instagram"
    site = "instagram.com"
    platform_label = "Instagram"
    content_type = ContentType.SOCIAL
    allowed_domains = ["instagram.com"]
    post_url_hints = ["/p/", "/reel/", "/tv/", "/explore/tags/"]
    query_templates = [
        'site:{site} inurl:/p/ "{q}"',
        'site:{site} "#وزارة_العمل" OR "{q}"',
        'site:{site} "وزارة العمل" العراق',
    ]

    async def fetch(self, item: dict):
        """Skip full page fetch for Instagram social posts — use snippet only."""
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