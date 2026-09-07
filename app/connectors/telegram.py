"""Public Telegram channel research via t.me web previews — no login."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from models import ContentType
from .base import DEFAULT_HEADERS
from .social import (
    SocialConnector,
    extract_hashtags,
    extract_mentions,
    is_noise_url,
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

    async def search(self, query: str, timelimit: str | None = None) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        try:
            for channel in OFFICIAL_CHANNELS:
                for item in await self._scrape_channel(channel, query):
                    url = item.get("url") or ""
                    if url and url not in seen and not is_noise_url(url):
                        seen.add(url)
                        results.append(item)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return results[:18]
        except Exception as exc:
            self.log_error("Telegram search failed", exc)

        # Official preview posts are enough. DuckDuckGo fallback only if scrape was empty.
        if results:
            return results[:18]

        try:
            for item in await super().search(query, timelimit=timelimit):
                url = item.get("url") or ""
                if not url or url in seen or is_noise_url(url):
                    continue
                seen.add(url)
                results.append(item)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return results[:18]
        except Exception as exc:
            self.log_error("Telegram index fallback failed", exc)

        return results[:18]

    async def _scrape_channel(self, channel: str, query: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        before: str | None = None
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=8,
            ) as client:
                for _ in range(2):
                    url = PREVIEW.format(channel=channel)
                    if before:
                        url = f"{url}?before={before}"
                    response = await client.get(url)
                    if response.status_code >= 400:
                        break
                    soup = BeautifulSoup(response.text, "html.parser")
                    page_items, last_post = self._parse_channel_page(soup, channel, query)
                    added = 0
                    for item in page_items:
                        post_url = item.get("url") or ""
                        if not post_url or post_url in seen:
                            continue
                        seen.add(post_url)
                        items.append(item)
                        added += 1
                    if not last_post or last_post == before or added == 0:
                        break
                    before = last_post
        except Exception as exc:
            self.log_error("Telegram channel scrape failed", exc)
            return items
        return items

    def _parse_channel_page(self, soup, channel: str, query: str) -> tuple[list[dict], str | None]:
        items: list[dict] = []
        last_post: str | None = None
        needles = [part.lower() for part in re.split(r"\s+", query or "") if len(part) > 1]
        ministry = any(
            token in (query or "").lower()
            for token in ("عمل", "labour", "labor", "molsa", "وزير", "وزارة")
        )
        for node in soup.select(".tgme_widget_message"):
            post_id = (node.get("data-post") or "").strip()
            if not post_id:
                continue
            last_post = post_id
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
                        "provenance": "verified",
                    },
                }
            )
        return items, last_post

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
