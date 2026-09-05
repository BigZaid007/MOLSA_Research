from models import ContentType
from .social import SocialConnector


class LinkedInConnector(SocialConnector):
    name = "linkedin"
    site = "linkedin.com"
    platform_label = "LinkedIn"
    content_type = ContentType.SOCIAL
    allowed_domains = ["linkedin.com"]
    post_url_hints = ["/posts/", "/feed/update/", "/pulse/"]
    query_templates = [
        'site:{site} inurl:posts "{q}"',
        'site:{site}/pulse "{q}"',
        'site:{site} "Ministry of Labour" Iraq',
        'site:{site} "وزارة العمل والشؤون الاجتماعية"',
    ]

    async def fetch(self, item: dict):
        """Skip full page fetch for LinkedIn social posts — use snippet only."""
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
