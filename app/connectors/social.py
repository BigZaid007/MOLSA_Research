"""Shared helpers for public social-media research (posts, tags, mentions, threads)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from models import ContentType
from services.focus import has_ministry_entity_phrase, title_names_other_ministry
from services.quality import filter_social_hits, is_hard_spam
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_text

# Known / likely public ministry-related handles and tags (Iraq)
MINISTRY_SOCIAL_HINTS = {
    "facebook": [
        "وزارة العمل والشؤون الاجتماعية",
        "وزير العمل العراقي",
        "MOLSA Iraq",
    ],
    "instagram": [
        "وزارة_العمل",
        "molsa",
        "وزارة العمل العراقية",
    ],
    "linkedin": [
        "Ministry of Labour and Social Affairs Iraq",
        "وزارة العمل والشؤون الاجتماعية",
        "MOLSA",
    ],
    "x": [
        "وزارة العمل",
        "وزير العمل",
        "Ministry of Labour Iraq",
    ],
    "tiktok": [
        "وزارة_العمل",
        "وزارة العمل العراق",
        "MOLSA",
    ],
    "reddit": [
        "Ministry of Labour Iraq",
        "وزارة العمل",
        "MOLSA",
    ],
    "telegram": [
        "وزارة العمل والشؤون الاجتماعية",
        "وزير العمل",
        "molsa2023",
    ],
}

NOISE_URL_PARTS = (
    "/login",
    "/signup",
    "/share.php",
    "/sharer.php",
    "/privacy",
    "/help/",
    "/about",
    "/settings",
    "accounts.",
    "/recover",
    "/legal",
)

KIND_RANK = {
    "thread": 0,
    "post": 1,
    "official": 2,
    "article": 3,
    "tag": 4,
    "mention": 5,
    "page": 6,
    "profile": 7,
    "subreddit": 8,
}


def extract_hashtags(text: str) -> list[str]:
    return re.findall(r"[#＃][\w\u0600-\u06FF_]+", text or "", flags=re.UNICODE)


def extract_mentions(text: str) -> list[str]:
    return re.findall(r"@[\w\u0600-\u06FF.]+", text or "", flags=re.UNICODE)


def is_noise_url(url: str) -> bool:
    low = (url or "").lower()
    if not low.startswith("http"):
        return True
    parsed = urlparse(low)
    if "t.me" in parsed.netloc or "telegram.me" in parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if parts[:1] == ["s"] and len(parts) < 3:
            return True
        if "before=" in (parsed.query or ""):
            return True
    return any(part in low for part in NOISE_URL_PARTS)


def is_official_social_url(url: str) -> bool:
    low = (url or "").lower()
    return "molsa2023" in low or "molsa.gov.iq" in low


def classify_social_url(url: str, platform: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    query = (parsed.query or "").lower()
    if platform == "x" or "twitter.com" in host or "x.com" in host:
        if "/status/" in path:
            return "post"
        if path.count("/") <= 2:
            return "profile"
        return "mention"
    if platform == "reddit":
        if "/comments/" in path:
            return "thread"
        if "/r/" in path and "/comments/" not in path:
            return "subreddit"
        return "post"
    if platform == "linkedin":
        if "/posts/" in path or "/feed/update/" in path:
            return "post"
        if "/pulse/" in path:
            return "article"
        if "/company/" in path or "/in/" in path:
            return "profile"
        return "post"
    if platform == "instagram":
        if "/p/" in path or "/reel/" in path or "/tv/" in path:
            return "post"
        if "/explore/tags/" in path or "/tags/" in path:
            return "tag"
        return "profile"
    if platform == "facebook":
        if (
            "/posts/" in path
            or "/permalink" in path
            or "/watch/" in path
            or "/videos/" in path
            or "/photos/" in path
            or "/share/p/" in path
            or "story.php" in path
            or "story_fbid" in query
        ):
            return "post"
        if "/hashtag/" in path:
            return "tag"
        return "page"
    if platform == "tiktok":
        if "/video/" in path:
            return "post"
        if "/tag/" in path:
            return "tag"
        return "profile"
    if platform == "telegram":
        parts = [p for p in path.split("/") if p and p != "s"]
        if len(parts) >= 2 and parts[-1].isdigit():
            return "post"
        return "official" if "molsa" in path else "page"
    return "post"


def hashtag_variants(topic: str) -> list[str]:
    """Turn a topic into plausible hashtag forms."""
    topic = (topic or "").strip()
    if not topic:
        return []
    cleaned = re.sub(r"[^\w\u0600-\u06FF\s]", " ", topic, flags=re.UNICODE)
    parts = [p for p in cleaned.split() if p]
    variants = []
    if parts:
        variants.append("#" + "_".join(parts[:6]))
    lowered = topic.lower()
    if "عمل" in topic or "labour" in lowered or "labor" in lowered or "molsa" in lowered:
        variants.extend(["#وزارة_العمل", "#وزارة_العمل_والشؤون_الاجتماعية", "#MOLSA"])
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _hit_score(item: dict, topic: str) -> int:
    kind = (item.get("metadata") or {}).get("post_kind", "post")
    score = 12 - KIND_RANK.get(kind, 9)
    blob = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    topic_l = (topic or "").lower()
    for token in ("وزارة العمل", "وزير العمل", "molsa", "ministry of labour", "ministry of labor"):
        if token in blob:
            score += 6
    if topic_l and topic_l[:18] in blob:
        score += 3
    if is_official_social_url(item.get("url") or ""):
        score += 8
    return score


class SocialConnector(PublicWebSearchConnector):
    """
    Social connector that hunts posts / tags / mentions / threads via `ddgs`.
    Does NOT fall back to Google News (that returns articles, not social posts).
    """

    content_type = ContentType.SOCIAL
    post_url_hints: list[str] = []
    query_templates: list[str] = []
    allowed_domains: list[str] = []

    async def search(self, query: str, timelimit: str | None = None) -> list[dict]:
        queries = self._build_social_queries(query)[:5]
        if not queries:
            return []
        domains = self._domains() or None
        results: list[dict] = []
        seen: set[str] = set()

        async def run_one(q: str, region: str) -> list[dict]:
            return await ddgs_text(
                q,
                source=self.name,
                max_results=8,
                allowed_domains=domains,
                region=region,
                timelimit=timelimit,
                timeout=9.0,
            )

        first = await run_one(queries[0], "xa-ar")
        batches = [first]
        if not first and len(queries) > 1:
            batches = [await run_one(queries[1], "xa-ar")]
        for batch in batches:
            if isinstance(batch, Exception) or not batch:
                continue
            for item in batch:
                url = item.get("url") or ""
                if not url or url in seen or is_noise_url(url):
                    continue
                if "news.google.com" in url:
                    continue
                seen.add(url)
                kind = classify_social_url(url, self.name)
                title = (item.get("title") or "").strip()
                snippet = (item.get("snippet") or "").strip()
                if title.lower().startswith("link to ") and snippet:
                    item["title"] = snippet[:120]
                    title = item["title"]
                if is_hard_spam(title, snippet, url, kind):
                    continue
                if title_names_other_ministry(title):
                    continue
                if not has_ministry_entity_phrase(title) and not has_ministry_entity_phrase(snippet):
                    continue
                text = f"{item.get('title', '')} {snippet}"
                item["source"] = self.name
                item["content_type"] = ContentType.SOCIAL.value
                item["metadata"] = {
                    "post_kind": kind,
                    "platform": self.platform_label,
                    "hashtags": extract_hashtags(text),
                    "mentions": extract_mentions(text),
                    "official": is_official_social_url(url),
                }
                results.append(item)

        results = filter_social_hits(results)
        results.sort(key=lambda item: _hit_score(item, query), reverse=True)
        preferred = [
            item
            for item in results
            if (item.get("metadata") or {}).get("post_kind") in {"thread", "post", "official", "article"}
        ]
        extras = [item for item in results if item not in preferred]
        return (preferred + extras)[:12]

    def _build_social_queries(self, topic: str) -> list[str]:
        topic = (topic or "").strip()
        site = self.site or ""
        queries: list[str] = []

        def add(q: str):
            q = q.strip()
            if q and q not in queries:
                queries.append(q)

        if site:
            add(f'site:{site} "{topic}"')
        else:
            add(f'"{topic}"')

        for template in self.query_templates[:4]:
            try:
                add(template.format(q=topic, site=site))
            except (KeyError, ValueError):
                continue

        for tag in hashtag_variants(topic)[:2]:
            if site:
                add(f"site:{site} {tag}")

        for hint in MINISTRY_SOCIAL_HINTS.get(self.name, [])[:2]:
            if site and hint.lower() not in topic.lower():
                add(f'site:{site} "{hint}"')

        return queries

    async def fetch(self, item: dict):
        research_item = await super().fetch(item)
        meta = item.get("metadata") or {}
        research_item.metadata.update(meta)
        tags = list(meta.get("hashtags") or [])
        mentions = list(meta.get("mentions") or [])
        blob = f"{research_item.title or ''} {research_item.description or ''} {research_item.content or ''}"
        tags = list(dict.fromkeys(tags + extract_hashtags(blob)))
        mentions = list(dict.fromkeys(mentions + extract_mentions(blob)))
        research_item.keywords = tags + mentions
        research_item.metadata["hashtags"] = tags
        research_item.metadata["mentions"] = mentions
        research_item.metadata["post_kind"] = meta.get("post_kind") or classify_social_url(
            research_item.url, self.name
        )
        research_item.content_type = ContentType.SOCIAL
        return research_item
