"""Public search over the Iraqi news-agency catalog."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from models import ContentType
from services.agencies import NewsAgency, match_agency, selected_agencies
from services.focus import agency_query_terms, has_ministry_entity_phrase, is_homepage_url, title_names_other_ministry
from services.quality import is_foreign_labour, is_hard_spam
from services.urls import canonicalize_url
from .base import PublicWebSearchConnector
from .ddgs_search import ddgs_news, ddgs_text

_FEED_CACHE: dict[str, list[str]] = {}

PRIORITY_AGENCY_IDS = (
    "ina",
    "nina",
    "shafaq",
    "alsumaria",
    "almada",
    "baghdad24",
    "rudaw",
    "mawazin",
    "nasnews",
    "imn",
    "alsharqiya",
    "almirbad",
    "kurdistan24",
    "alforat",
    "iraqinews",
    "alghadpress",
    "utv",
    "dijlah",
    "nrt",
)
# Direct site: searches that actually return ministry hits. Everything else is
# RSS + one batched OR query so DuckDuckGo is not flooded.
DEDICATED_AGENCY_IDS = ("ina", "nina", "shafaq", "alsumaria")
PRIORITY_CAP = 6
OTHER_CAP = 3
TOTAL_CAP = 80

KNOWN_AGENCY_FEEDS: dict[str, tuple[str, ...]] = {
    "ina": ("https://www.ina.iq/rss.xml",),
    "rudaw": ("https://www.rudaw.net/arabic/rss.xml",),
    "nina": ("https://ninanews.com/rss.xml",),
    "shafaq": ("https://shafaq.com/ar/rss", "https://www.shafaq.com/feed"),
    "alsumaria": ("https://www.alsumaria.tv/rss", "https://www.alsumaria.tv/rss.xml"),
    "almada": ("https://almadapaper.net/feed",),
    "baghdad24": ("https://baghdad24.news/feed",),
    "mawazin": ("https://www.mawazin.net/rss",),
    "nasnews": ("https://www.nasnews.com/rss",),
    "kurdistan24": ("https://www.kurdistan24.net/ar/rss",),
    "iraqinews": ("https://www.iraqinews.com/feed/",),
    "alghadpress": ("https://www.alghadpress.com/feed",),
}

MINISTRY_FEED_TOKENS = (
    "وزارة العمل",
    "وزير العمل",
    "الشؤون الاجتماعية",
    "molsa",
    "ministry of labour",
    "ministry of labor",
)


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _query_tokens(query: str) -> list[str]:
    return [part for part in query.replace(",", " ").split() if len(part) > 2][:6]


def _keep_item(title: str, snippet: str, url: str, agency: NewsAgency | None) -> bool:
    if is_hard_spam(title, snippet, url, "article"):
        return False
    if is_homepage_url(url):
        return False
    if title_names_other_ministry(title):
        return False
    if not has_ministry_entity_phrase(f"{title} {snippet}"):
        return False
    if agency and not agency.local_iraqi:
        blob = f"{title} {snippet} {url}"
        iraq = any(
            token in blob.lower()
            for token in ("العراق", "العراقي", "العراقية", "iraq", "iraqi", "molsa", "بغداد")
        )
        if iraq:
            return True
        return not is_foreign_labour(title, snippet, url)
    return not is_foreign_labour(title, snippet, url)


def _recent_enough(published: datetime | None, timelimit: str | None) -> bool:
    if not published or not timelimit:
        return True
    windows = {"d": 2, "w": 7, "m": 31, "y": 365}
    days = windows.get((timelimit or "").lower())
    if days is None:
        return True
    return published >= datetime.now() - timedelta(days=days)


def _matches_ministry(title: str, summary: str, query: str = "") -> bool:
    if title_names_other_ministry(title):
        return False
    blob = f"{title} {summary}".lower()
    if any(token.lower() in blob for token in MINISTRY_FEED_TOKENS):
        return True
    return has_ministry_entity_phrase(blob)


class AgenciesConnector(PublicWebSearchConnector):
    name = "agencies"
    site = None
    platform_label = "News agencies"
    content_type = ContentType.NEWS

    def __init__(self) -> None:
        self.selected_ids: list[str] | None = None

    async def search(self, query: str, timelimit: str | None = None) -> list[dict]:
        agencies = selected_agencies(self.selected_ids)
        query = (query or "").strip()
        if not query or not agencies:
            return []

        short = agency_query_terms(query)
        by_id = {agency.id: agency for agency in agencies}
        iraqi = [
            by_id[item]
            for item in PRIORITY_AGENCY_IDS
            if item in by_id
        ]
        extra_iraqi = [
            agency
            for agency in agencies
            if agency.local_iraqi and agency.id not in PRIORITY_AGENCY_IDS
        ]
        iraqi.extend(extra_iraqi)
        foreign = [agency for agency in agencies if not agency.local_iraqi]

        dedicated = [agency for agency in iraqi if agency.id in DEDICATED_AGENCY_IDS]
        batched = [agency for agency in iraqi if agency.id not in DEDICATED_AGENCY_IDS]

        jobs = [
            self._feed_fallback(short, agency, timelimit)
            for agency in iraqi
            if agency.id in KNOWN_AGENCY_FEEDS
        ]
        for agency in dedicated:
            jobs.append(self._site_search(short, agency.domains[0], timelimit))
        rest_domains = [agency.domains[0] for agency in batched if agency.domains]
        if rest_domains:
            jobs.append(self._or_site_search(short, rest_domains, timelimit))
        if foreign:
            domains = [agency.domains[0] for agency in foreign if agency.domains]
            if domains:
                jobs.append(self._or_site_search(short, domains, timelimit))
        jobs.append(self._google_news_search(f"{short} العراق", limit=10, timelimit=timelimit))

        batches = await asyncio.gather(*jobs, return_exceptions=True)
        results: list[dict] = []
        seen: set[str] = set()

        def absorb(batch) -> None:
            if isinstance(batch, Exception) or not batch:
                return
            for item in batch:
                stamped = self._stamp(item, agencies)
                if not stamped:
                    continue
                key = canonicalize_url(stamped.get("url") or "") or stamped.get("url")
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(stamped)

        for batch in batches:
            absorb(batch)

        return self._cap_by_agency(results)

    def _cap_by_agency(self, results: list[dict]) -> list[dict]:
        taken: dict[str, int] = {}
        kept: list[dict] = []
        leftover: list[dict] = []
        for item in results:
            agency_id = (item.get("metadata") or {}).get("agency_id") or ""
            cap = PRIORITY_CAP if agency_id in PRIORITY_AGENCY_IDS else OTHER_CAP
            if taken.get(agency_id, 0) < cap:
                kept.append(item)
                taken[agency_id] = taken.get(agency_id, 0) + 1
            else:
                leftover.append(item)
        for item in leftover:
            if len(kept) >= TOTAL_CAP:
                break
            kept.append(item)
        return kept[:TOTAL_CAP]

    async def _site_search(
        self, query: str, domain: str, timelimit: str | None = None
    ) -> list[dict]:
        return await ddgs_text(
            f"site:{domain} {query}",
            source=self.name,
            max_results=8,
            allowed_domains=[domain],
            region="xa-ar",
            timelimit=timelimit,
            timeout=8.0,
        )

    async def _or_site_search(
        self, query: str, domains: list[str], timelimit: str | None = None
    ) -> list[dict]:
        clause = " OR ".join(f"site:{domain}" for domain in domains)
        return await ddgs_text(
            f"{query} ({clause})",
            source=self.name,
            max_results=8,
            allowed_domains=domains,
            region="xa-ar",
            timelimit=timelimit,
            timeout=8.0,
        )

    async def _name_fallback(
        self, query: str, agency: NewsAgency, timelimit: str | None = None
    ) -> list[dict]:
        hits = await ddgs_news(
            f"{query} {agency.label_ar}",
            source=self.name,
            max_results=6,
            region="xa-ar",
            timelimit=timelimit or "d",
            timeout=8.0,
        )
        kept = []
        for item in hits:
            url = item.get("url") or ""
            matched = match_agency(url)
            if matched and matched.id == agency.id:
                kept.append(item)
            elif any(domain in url.lower() for domain in agency.domains):
                kept.append(item)
            elif "news.google.com" in url.lower():
                blob = f"{item.get('title', '')} {item.get('source_title', '')}"
                if agency.label_ar in blob or agency.label_en.lower() in blob.lower():
                    kept.append(item)
        return kept

    async def _feed_fallback(
        self, query: str, agency: NewsAgency, timelimit: str | None = None
    ) -> list[dict]:
        feeds = list(KNOWN_AGENCY_FEEDS.get(agency.id) or [])
        cached = _FEED_CACHE.get(agency.id)
        if cached is None and not feeds:
            try:
                from trafilatura.feeds import find_feed_urls

                homepage = f"https://{agency.domains[0]}"
                discovered = await asyncio.to_thread(find_feed_urls, homepage, target_lang="ar")
                feeds = list(discovered or [])[:2]
            except Exception:
                feeds = []
            _FEED_CACHE[agency.id] = feeds
        elif cached:
            for url in cached:
                if url not in feeds:
                    feeds.append(url)
        if not feeds:
            return []
        import feedparser

        hits: list[dict] = []
        for feed_url in feeds:
            try:
                parsed = await asyncio.to_thread(feedparser.parse, feed_url)
            except Exception:
                continue
            for entry in list(getattr(parsed, "entries", []) or [])[:20]:
                title = str(getattr(entry, "title", "") or "")
                link = str(getattr(entry, "link", "") or "")
                summary = str(getattr(entry, "summary", "") or "")
                if not _matches_ministry(title, summary, query):
                    continue
                published = None
                raw_date = getattr(entry, "published", None)
                if raw_date:
                    try:
                        published = parsedate_to_datetime(raw_date).replace(tzinfo=None)
                    except Exception:
                        published = None
                if not _recent_enough(published, timelimit):
                    continue
                hits.append(
                    {
                        "title": title,
                        "url": link,
                        "snippet": summary[:240],
                        "source": self.name,
                        "published_date": published,
                    }
                )
                if len(hits) >= 8:
                    return hits
        if feeds:
            _FEED_CACHE[agency.id] = feeds
        return hits

    def _match_from_google_news(self, item: dict, agencies: list[NewsAgency]) -> NewsAgency | None:
        blob = " ".join(
            [
                item.get("title") or "",
                item.get("snippet") or "",
                item.get("source_title") or "",
            ]
        )
        blob_l = blob.lower()
        for agency in agencies:
            if agency.label_ar and agency.label_ar in blob:
                return agency
            if agency.label_en and agency.label_en.lower() in blob_l:
                return agency
            if any(domain in blob_l for domain in agency.domains):
                return agency
        if "واع" in blob or " ina" in f" {blob_l}" or blob_l.endswith("ina"):
            for agency in agencies:
                if agency.id == "ina":
                    return agency
        return None

    def _stamp(self, item: dict, agencies: list[NewsAgency]) -> dict | None:
        url = item.get("url") or ""
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        if not url or not title:
            return None
        agency = match_agency(url)
        if agency is None:
            host = _host(url)
            for candidate in agencies:
                if any(domain in host for domain in candidate.domains):
                    agency = candidate
                    break
        if agency is None and "news.google.com" in url.lower():
            agency = self._match_from_google_news(item, agencies)
        if agency is None:
            return None
        if agency.id not in {candidate.id for candidate in agencies}:
            return None
        if not _keep_item(title, snippet, url, agency):
            return None
        item["source"] = self.name
        item["platform"] = agency.id
        item["agency_label"] = agency.label_ar
        item["content_type"] = ContentType.NEWS.value
        item["metadata"] = {
            "agency_id": agency.id,
            "agency_label": agency.label_ar,
            "platform": agency.label_ar,
        }
        return item
