from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from models import ContentType, ResearchItem
from .base import DEFAULT_HEADERS
from .ddgs_search import ddgs_text
from .social import SocialConnector, extract_hashtags, extract_mentions


class RedditConnector(SocialConnector):
    name = "reddit"
    site = "reddit.com"
    platform_label = "Reddit"
    content_type = ContentType.FORUM
    allowed_domains = ["reddit.com"]
    post_url_hints = ["/comments/"]
    query_templates = [
        'site:{site} inurl:comments "{q}"',
        'site:{site}/r/iraq "{q}"',
        'site:{site} "Ministry of Labour" Iraq',
        'site:{site} "وزارة العمل"',
    ]

    async def search(self, query: str) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        # 1) Optional PRAW if credentials present
        praw_results = await self._search_praw(query)
        for item in praw_results:
            url = item.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                results.append(item)

        # 2) Anonymous Reddit JSON — Arabic, English, and Iraq subs
        if len(results) < 8:
            for variant in self._reddit_queries(query):
                json_results = await self._search_json(variant)
                for item in json_results:
                    url = item.get("url") or ""
                    if url and url not in seen:
                        seen.add(url)
                        results.append(item)
                if len(results) >= 10:
                    break

        # 3) ddgs site:reddit.com for more threads / mentions
        web_results = await super().search(query)
        for item in web_results:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            item["content_type"] = ContentType.FORUM.value
            results.append(item)

        if not results:
            # Last resort plain ddgs
            fallback = await ddgs_text(
                f'site:reddit.com "{query}"',
                source=self.name,
                max_results=10,
                allowed_domains=["reddit.com"],
                region="wt-wt",
            )
            for item in fallback:
                item["content_type"] = ContentType.FORUM.value
                item["metadata"] = {
                    "post_kind": "thread" if "/comments/" in item.get("url", "") else "post",
                    "platform": "Reddit",
                }
                results.append(item)

        return results[:18]

    def _reddit_queries(self, query: str) -> list[str]:
        q = (query or "").strip()
        variants = [q, f"{q} Iraq", f'subreddit:iraq {q}']
        if "عمل" in q or "labour" in q.lower() or "labor" in q.lower():
            variants.extend(
                [
                    "Ministry of Labour Iraq",
                    "وزارة العمل العراق",
                    "MOLSA Iraq",
                ]
            )
        out: list[str] = []
        for item in variants:
            if item and item not in out:
                out.append(item)
        return out[:4]

    async def _search_json(self, query: str) -> list[dict]:
        results: list[dict] = []
        try:
            async with httpx.AsyncClient(
                headers={**DEFAULT_HEADERS, "User-Agent": "ResearchDataFetcher/1.0"},
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    "https://www.reddit.com/search.json",
                    params={
                        "q": query,
                        "limit": 15,
                        "sort": "relevance",
                        "t": "year",
                        "type": "link",
                    },
                    timeout=15,
                )
                if response.status_code >= 400:
                    return []
                data = response.json()
                for post in data.get("data", {}).get("children", []):
                    post_data = post.get("data", {})
                    permalink = post_data.get("permalink") or ""
                    url = (
                        f"https://www.reddit.com{permalink}"
                        if permalink
                        else post_data.get("url")
                    )
                    if not url:
                        continue
                    created = post_data.get("created_utc")
                    published = (
                        datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None)
                        if created
                        else None
                    )
                    selftext = post_data.get("selftext") or ""
                    title = post_data.get("title", "")
                    text = f"{title} {selftext}"
                    results.append(
                        {
                            "title": title,
                            "url": url,
                            "snippet": (selftext[:240] + "...") if len(selftext) > 240 else selftext,
                            "source": self.name,
                            "published_date": published,
                            "author": post_data.get("author"),
                            "content_type": ContentType.FORUM.value,
                            "metadata": {
                                "post_kind": "thread",
                                "platform": "Reddit",
                                "subreddit": post_data.get("subreddit"),
                                "score": post_data.get("score"),
                                "num_comments": post_data.get("num_comments"),
                                "hashtags": extract_hashtags(text),
                                "mentions": extract_mentions(text),
                            },
                        }
                    )
        except Exception as exc:
            self.log_error("Reddit JSON search failed", exc)
        return results

    async def _search_praw(self, query: str) -> list[dict]:
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        user_agent = os.getenv("REDDIT_USER_AGENT", "ResearchDataFetcher/1.0").strip()
        if not client_id or not client_secret:
            return []

        try:
            import asyncio
            import praw

            def _run() -> list[dict]:
                reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=user_agent,
                )
                out: list[dict] = []
                for submission in reddit.subreddit("all").search(query, limit=10, sort="relevance"):
                    out.append(
                        {
                            "title": submission.title,
                            "url": f"https://www.reddit.com{submission.permalink}",
                            "snippet": (submission.selftext or "")[:240],
                            "source": self.name,
                            "published_date": datetime.fromtimestamp(
                                submission.created_utc, tz=timezone.utc
                            ).replace(tzinfo=None),
                            "author": str(submission.author) if submission.author else None,
                            "content_type": ContentType.FORUM.value,
                            "metadata": {
                                "post_kind": "thread",
                                "platform": "Reddit",
                                "subreddit": str(submission.subreddit),
                                "score": submission.score,
                                "num_comments": submission.num_comments,
                                "via": "praw",
                            },
                        }
                    )
                return out

            return await asyncio.to_thread(_run)
        except Exception as exc:
            self.log_error("PRAW search failed", exc)
            return []

    async def fetch(self, item: dict):
        """Skip full page fetch for Reddit — use snippet only."""
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
        research_item.content_type = ContentType.FORUM
        research_item.metadata.update(meta)
        return research_item
