from models import ContentType
from .social import SocialConnector


class FacebookConnector(SocialConnector):
    name = "facebook"
    site = "facebook.com"
    platform_label = "Facebook"
    content_type = ContentType.SOCIAL
    allowed_domains = ["facebook.com", "fb.com", "fb.watch"]
    post_url_hints = ["/posts/", "/permalink", "/watch/", "/videos/", "/photos/", "/hashtag/"]
    query_templates = [
        'site:{site} inurl:posts "{q}"',
        'site:{site} inurl:story.php "{q}"',
        'site:{site} inurl:permalink "{q}"',
        'site:{site} "{q}" (منشور OR post)',
    ]

    async def fetch(self, item: dict):
        """Skip full page fetch for Facebook social posts — use snippet only."""
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