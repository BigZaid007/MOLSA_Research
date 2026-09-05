"""Public Telegram channel research via t.me web previews — no login."""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from models import ContentType
from .base import DEFAULT_HEADERS
from .ddgs_search import ddgs_text
from .social import (
    SocialConnector,
    classify_social_url,
    extract_hashtags,
    extract_mentions,
    is_official_social_url,
)

OFFICIAL_CHANNELS = ("molsa2023",)
PREVIEW = "https://t.me/s/{channel}"


class TelegramConnector(SocialConnector):
    name = "telegram"
    site = "t.me"
    platform_label = "Telegram"
    content_type = ContentType.SOCIAL
    allowed_domains = ["t.me", "telegram.me", "telegram.org"]
    post_url_hints = ["/s/"]
    query_templates = [
        'site:t.me "{q}"',
        'site:t.me/s/molsa2023 "{q}"',
        'site:t.me "وزارة العمل" العراق',
    ]

    async def search(self, query: str) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        for channel in OFFICIAL_CHANNELS:
            for item in await self._scrape_channel(channel, query):
                url = item.get("url") or ""
                if url and url not in seen:
                    seen.add(url)
                    results.append(item)

        if len(results) < 8:
            for item in await super().search(query):
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(item)

        if not results:
            fallback = await ddgs_text(
                f'site:t.me "{query}"',
                source=self.name,
                max_results=10,
                allowed_domains=self.allowed_domains,
                region="xa-ar",
            )
            for item in fallback:
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                item["source"] = self.name
                item["content_type"] = ContentType.SOCIAL.value
                item["metadata"] = {
                    "post_kind": classify_social_url(url, "telegram"),
                    "platform": "Telegram",
                    "official": is_official_social_url(url),
                }
                results.append(item)

        return results[:18]

    async def _scrape_channel(self, channel: str, query: str) -> list[dict]:
        items: list[dict] = []
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=12,
            ) as client:
                response = await client.get(PREVIEW.format(channel=channel))
                if response.status_code >= 400:
                    return []
                soup = BeautifulSoup(response.text, "html.parser")
        except Exception as exc:
            self.log_error("Telegram channel scrape failed", exc)
            return []

        needles = [part.lower() for part in re.split(r"\s+", query or "") if len(part) > 1]
        ministry = any(
            token in (query or "").lower()
            for token in ("عمل", "labour", "labor", "molsa", "وزير", "وزارة")
        )

        for node in soup.select(".tgme_widget_message"):
            post_id = (node.get("data-post") or "").strip()
            if not post_id:
                continue
            url = f"https://t.me/{post_id}"
            text_el = node.select_one(".tgme_widget_message_text")
            text = text_el.get_text(" ", strip=True) if text_el else ""
            if not text:
                continue
            blob = text.lower()
            if needles and not ministry and not any(n in blob for n in needles):
                continue
            time_el = node.select_one("time")
            published = None
            if time_el and time_el.get("datetime"):
                try:
                    published = datetime.fromisoformat(
                        time_el["datetime"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    published = None
            title = text.split("\n", 1)[0][:140]
            items.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": text[:420],
                    "source": self.name,
                    "published_date": published,
                    "author": "وزارة العمل والشؤون الاجتماعية",
                    "content_type": ContentType.SOCIAL.value,
                    "metadata": {
                        "post_kind": "post",
                        "platform": "Telegram",
                        "channel": channel,
                        "official": True,
                        "hashtags": extract_hashtags(text),
                        "mentions": extract_mentions(text),
                        "via": "telegram_preview",
                    },
                }
            )
        return items

    async def fetch(self, item: dict):
        from .base import BaseConnector

        snippet = item.get("snippet") or item.get("title") or ""
        meta = item.get("metadata") or {}
        research_item = BaseConnector.to_item(
            self,
            {
                **item,
                "content": snippet,
                "content_type": self.content_type.value,
                "status": "partial",
                "metadata": {**meta, "fetch_mode": "telegram_preview"},
            },
        )
        research_item.metadata.update(meta)
        return research_item
