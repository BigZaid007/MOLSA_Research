import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Set

SOURCE_TIMEOUT_SECONDS = 16
GLOBAL_TIMEOUT_SECONDS = 22
SOCIAL_SOURCE_TIMEOUT_SECONDS = 18
SOCIAL_GLOBAL_TIMEOUT_SECONDS = 28
FETCH_PAGE_TIMEOUT = 8
FETCH_CONCURRENCY = 8
FETCH_GLOBAL_TIMEOUT = 35
WEB_SOURCE_LIST = ["rss", "news", "google", "bing"]
SOCIAL_SOURCE_LIST = ["facebook", "instagram", "linkedin", "x", "tiktok", "reddit", "telegram"]
EXPLORATORY_SOCIAL_LIST = ["facebook", "instagram", "linkedin", "x", "tiktok", "reddit"]
AGENCY_SOURCE_LIST = ["agencies"]
TRUSTED_SOURCE_ORDER = ["rss", "news", "agencies", "telegram"]
GAPFILL_SOURCE_LIST = ["google", "bing"]
SOCIAL_SOURCES = set(SOCIAL_SOURCE_LIST)
EXPLORATORY_SOCIAL = set(EXPLORATORY_SOCIAL_LIST)
WEB_SOURCES = set(WEB_SOURCE_LIST)
AGENCY_SOURCES = set(AGENCY_SOURCE_LIST)
GAPFILL_SOURCES = set(GAPFILL_SOURCE_LIST)
DEFAULT_ALL_SOURCE_LIST = ["rss", "news", "google", "bing", "agencies", "telegram"]
ALL_SOURCE_LIST = WEB_SOURCE_LIST + AGENCY_SOURCE_LIST + SOCIAL_SOURCE_LIST
ALL_SOURCES = set(ALL_SOURCE_LIST)
ALL_GLOBAL_TIMEOUT_SECONDS = 42
AGENCY_GROUP_TIMEOUT_SECONDS = 32
TRUSTED_MIN_ITEMS = 8
QUERY_LIMIT = 3
GROUP_TIMEOUTS = {
    "web": GLOBAL_TIMEOUT_SECONDS,
    "social": SOCIAL_GLOBAL_TIMEOUT_SECONDS,
    "agencies": AGENCY_GROUP_TIMEOUT_SECONDS,
    "trusted": 34,
    "gapfill": GLOBAL_TIMEOUT_SECONDS,
}


def resolve_sources(content_type: str, selected: list[str] | None = None) -> list[str]:
    """Pick connectors for a search tab. All defaults to web + agencies + Telegram."""
    kind = (content_type or "all").lower()
    picked = [source for source in (selected or []) if source]
    if kind == "social":
        return [source for source in picked if source in SOCIAL_SOURCES] or list(SOCIAL_SOURCE_LIST)
    if kind == "agencies":
        return list(AGENCY_SOURCE_LIST)
    if kind in {"", "all"}:
        chosen = [source for source in picked if source in ALL_SOURCES]
        return chosen or list(DEFAULT_ALL_SOURCE_LIST)
    return [source for source in picked if source in WEB_SOURCES] or list(WEB_SOURCE_LIST)


def search_queries_for_run(queries: list[str], topic: str) -> list[str]:
    return (queries or [topic])[:QUERY_LIMIT]


def split_source_waves(sources: list[str]) -> dict[str, list[str]]:
    ordered = list(sources)
    trusted = [source for source in TRUSTED_SOURCE_ORDER if source in ordered]
    trusted += [source for source in ordered if source in TRUSTED_SOURCE_ORDER and source not in trusted]
    gapfill = [source for source in ordered if source in GAPFILL_SOURCES]
    exploratory = [source for source in ordered if source in EXPLORATORY_SOCIAL]
    leftover = [
        source
        for source in ordered
        if source not in set(trusted) | set(gapfill) | set(exploratory)
    ]
    return {
        "trusted": trusted + leftover,
        "gapfill": gapfill,
        "exploratory": exploratory,
    }


def grouped_sources(sources: list[str]) -> dict[str, list[str]]:
    return {
        "web": [source for source in sources if source in WEB_SOURCES],
        "social": [source for source in sources if source in SOCIAL_SOURCES],
        "agencies": [source for source in sources if source in AGENCY_SOURCES],
    }

from models import ResearchItem
from extractors import (
    MIN_BODY_CHARS,
    ContentExtractor,
    ContentCleaner,
    DataParser,
    extract_from_html,
    make_excerpt,
)
from connectors.base import BaseConnector
from connectors.registry import get_connector
from services.focus import (
    ARTICLE_HUBS,
    MINISTRY_RESULT_CAP,
    MINISTRY_LISTING_PAGES,
    build_search_queries,
    ddgs_timelimit,
    filter_ministry_results,
    has_ministry_entity,
    is_homepage_url,
    is_ministry_topic,
    is_official_domain,
    is_trusted_item,
    is_trusted_news_domain,
    item_provenance,
    ministry_relevance_score,
    province_terms,
    should_skip_html_fetch,
)
from services.quality import filter_research_items
from services.ranking import bm25_scores
from services.semantic import semantic_status, similarity_scores, wait_for_semantic_ranker
from services.urls import canonicalize_url

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    start_time: datetime
    end_time: datetime
    connectors_used: List[str]
    pages_crawled: int
    items_processed: int
    duplicates_found: int
    errors: int
    execution_time: float = 0.0

    def __post_init__(self):
        self.execution_time = (self.end_time - self.start_time).total_seconds()


class ResearchProcessor:
    def __init__(self):
        self.active_tasks: Dict[str, Dict] = {}
        self.results_storage: Dict[str, List[dict]] = {}

        self.extractor = ContentExtractor()
        self.cleaner = ContentCleaner()
        self.parser = DataParser()

    async def process_research(
        self,
        topic: str,
        sources: List[str],
        max_results: int,
        settings,
        date_from: str | None = None,
        date_to: str | None = None,
        content_type: str = "all",
        province: str | None = None,
        agencies: list[str] | None = None,
    ) -> str:
        """Start a research task."""
        task_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.active_tasks[task_id] = {
            "id": task_id,
            "topic": topic,
            "sources": sources,
            "max_results": max_results,
            "date_from": date_from,
            "date_to": date_to,
            "content_type": content_type,
            "province": (province or "").strip() or None,
            "agencies": list(agencies or []),
            "status": "pending",
            "start_time": datetime.now(),
            "settings": settings,
            "results": [],
            "stats": None,
            "error": None,
            "message": None,
            "date_filter_relaxed": False,
            "semantic": "loading",
        }

        return task_id

    async def start_processing(self, task_id: str):
        """Execute the research processing."""
        if task_id not in self.active_tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.active_tasks[task_id]
        task["status"] = "processing"
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        errors = 0

        try:
            topic = task["topic"]
            queries = build_search_queries(
                topic,
                task.get("date_from"),
                task.get("date_to"),
                task.get("province"),
            )
            logger.info("Search queries: %s", queries)

            content_type = (task.get("content_type") or "all").lower()
            sources = resolve_sources(content_type, task.get("sources"))
            timelimit = ddgs_timelimit(task.get("date_from"), task.get("date_to"))

            collected: List[ResearchItem] = []

            ranker_status = wait_for_semantic_ranker(timeout=6.0)
            task["semantic"] = ranker_status
            if content_type == "social":
                global_timeout = SOCIAL_GLOBAL_TIMEOUT_SECONDS
            elif content_type == "all":
                global_timeout = ALL_GLOBAL_TIMEOUT_SECONDS
            else:
                global_timeout = GLOBAL_TIMEOUT_SECONDS

            async def run_source(source: str) -> List[ResearchItem]:
                logger.info("Processing source: %s", source)
                if source in {"agencies", "rss", "telegram"}:
                    source_queries = search_queries_for_run(queries, topic)[:1]
                else:
                    source_queries = search_queries_for_run(queries, topic)
                bucket: List[ResearchItem] = []
                for query in source_queries:
                    batch = await self._process_source(
                        query,
                        source,
                        task["max_results"],
                        task.get("agencies"),
                        timelimit=timelimit,
                    )
                    bucket.extend(batch)
                    if len(bucket) >= task["max_results"]:
                        break
                return bucket[: task["max_results"] * 2]

            def _source_timeout(source: str) -> float:
                if source == "agencies":
                    return float(AGENCY_GROUP_TIMEOUT_SECONDS)
                if source == "telegram":
                    return 22.0
                if source in {"rss", "news"}:
                    return float(GLOBAL_TIMEOUT_SECONDS)
                if source in EXPLORATORY_SOCIAL:
                    return float(SOCIAL_SOURCE_TIMEOUT_SECONDS)
                return float(SOURCE_TIMEOUT_SECONDS)

            async def run_source_safe(source: str) -> List[ResearchItem]:
                try:
                    batch = await asyncio.wait_for(
                        run_source(source), _source_timeout(source)
                    )
                    collected.extend(batch)
                    self._publish_partial(task, collected)
                    return batch
                except asyncio.TimeoutError:
                    logger.warning(
                        "Source %s timed out after %ss",
                        source,
                        _source_timeout(source),
                    )
                    return []
                except Exception as exc:
                    logger.error(
                        "Error processing source %s: %s",
                        source,
                        exc or type(exc).__name__,
                    )
                    return []

            hub_task = None
            if content_type != "social" and is_ministry_topic(topic):
                hub_task = asyncio.create_task(self._discover_hub_articles())

            waves = split_source_waves(sources)

            async def run_named_sources(names: list[str], timeout: float) -> None:
                nonlocal errors
                if not names:
                    return
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            *[run_source_safe(source) for source in names],
                            return_exceptions=True,
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    errors += 1
                    logger.warning("Source wave timed out after %ss (%s)", timeout, names)

            if content_type == "social":
                await run_named_sources(sources, SOCIAL_GLOBAL_TIMEOUT_SECONDS)
            else:
                await run_named_sources(
                    waves["trusted"], GROUP_TIMEOUTS.get("trusted", global_timeout)
                )
                trusted_hits = [item for item in collected if is_trusted_item(item)]
                if waves["gapfill"] and (
                    len(trusted_hits) < TRUSTED_MIN_ITEMS or not waves["trusted"]
                ):
                    await run_named_sources(
                        waves["gapfill"], GROUP_TIMEOUTS.get("gapfill", global_timeout)
                    )
                if waves["exploratory"]:
                    await run_named_sources(
                        waves["exploratory"], SOCIAL_GLOBAL_TIMEOUT_SECONDS
                    )

            all_results = collected
            if content_type != "social" and is_ministry_topic(topic) and hub_task is not None:
                try:
                    all_results.extend(await asyncio.wait_for(hub_task, timeout=12))
                except Exception as exc:
                    logger.debug("Hub discovery skipped: %s", exc)
                    hub_task.cancel()
            for item in all_results:
                if (item.source or "").lower() in SOCIAL_SOURCES:
                    item.metadata.setdefault("post_kind", "post")
                    item.metadata["status"] = "partial"
            if content_type == "social":
                enriched_results = all_results
            else:
                enriched_results = await self._enrich_articles(
                    all_results, max_results=task["max_results"]
                )
            all_results = enriched_results

            cleaned_results = await self._clean_results(all_results)
            cleaned_results = filter_research_items(cleaned_results)
            deduped_results = self._remove_duplicates(
                cleaned_results, seen_urls, seen_titles
            )
            # Prefer ministry entity results over generic "work in Iraq"
            if is_ministry_topic(topic):
                deduped_results = filter_ministry_results(deduped_results, topic)
                logger.info(
                    "Ministry focus kept %s results for topic: %s",
                    len(deduped_results),
                    topic,
                )

            before_date = list(deduped_results)
            filtered_results = self._filter_by_date(
                deduped_results,
                task.get("date_from"),
                task.get("date_to"),
                topic=topic,
            )

            message = None
            date_filter_relaxed = False
            if (
                not filtered_results
                and before_date
                and (task.get("date_from") or task.get("date_to"))
            ):
                message = (
                    "No ministry results were found inside your selected date range."
                )
                logger.info("Date window empty for task %s; not restoring off-range hits", task_id)

            typed_results = self._filter_by_content_type(filtered_results, content_type)
            sorted_results = self._rank_results(typed_results, topic, task.get("province"))
            for item in sorted_results:
                item.metadata["provenance"] = item_provenance(item)
            serialized = [self._serialize_item(item) for item in sorted_results]

            task["results"] = serialized
            task["status"] = "completed"
            task["message"] = message
            task["date_filter_relaxed"] = date_filter_relaxed
            task["semantic"] = semantic_status()
            task["end_time"] = datetime.now()
            self.results_storage[task_id] = serialized

            try:
                task["stats"] = ProcessingStats(
                    start_time=task["start_time"],
                    end_time=task["end_time"],
                    connectors_used=task["sources"],
                    pages_crawled=len(all_results),
                    items_processed=len(sorted_results),
                    duplicates_found=max(0, len(all_results) - len(deduped_results)),
                    errors=errors,
                )
            except Exception as stats_error:
                logger.warning("Could not build stats for %s: %s", task_id, stats_error)
                task["stats"] = {
                    "pages_crawled": len(all_results),
                    "items_processed": len(sorted_results),
                    "errors": errors,
                }

            logger.info(
                "Task %s completed with %s results", task_id, len(sorted_results)
            )

        except Exception as e:
            logger.error("Error processing task %s: %s", task_id, e)
            # Keep any partial results if we already stored some
            if not task.get("results"):
                task["results"] = []
            task["status"] = "error"
            task["error"] = str(e)

    async def _process_source(
        self,
        topic: str,
        source: str,
        max_results: int,
        agencies: list[str] | None = None,
        timelimit: str | None = None,
    ) -> List[ResearchItem]:
        connector = get_connector(source)
        if not connector:
            logger.warning("No connector registered for source: %s", source)
            return []
        if source == "agencies" and hasattr(connector, "selected_ids"):
            connector.selected_ids = agencies or None

        if hasattr(connector, "is_available") and not await connector.is_available():
            logger.warning("Connector %s is not available", source)
            return []

        search_results = await connector.search(topic, timelimit=timelimit) or []
        cap = max(max_results, 12)
        if source == "agencies":
            cap = max(max_results * 2, 24)
        search_results = search_results[:cap]

        results: List[ResearchItem] = []
        for search_result in search_results:
            try:
                if not isinstance(search_result, dict):
                    continue
                is_social = source in SOCIAL_SOURCES or should_skip_html_fetch(
                    search_result.get("url") or ""
                )
                metadata = dict(search_result.get("metadata") or {})
                if is_social:
                    metadata.setdefault("post_kind", "post")
                    metadata["indexed"] = True
                    if source in EXPLORATORY_SOCIAL:
                        metadata["status"] = "partial"
                        metadata["exploratory"] = True
                research_item = BaseConnector.to_item(
                    connector,
                    {
                        **search_result,
                        "source": source,
                        "content": search_result.get("snippet") or search_result.get("title"),
                        "status": "partial" if is_social else "pending",
                        "metadata": metadata,
                    },
                )
                if isinstance(research_item, ResearchItem) and research_item.is_valid:
                    results.append(research_item)
            except Exception as e:
                logger.error("Failed to map %s result: %s", source, e)

        logger.info("Source %s: %s results", source, len(results))
        return results

    def _official_seed_items(self) -> List[ResearchItem]:
        """Unused homepage seeds — listing crawl lives in _discover_hub_articles."""
        return []

    async def _discover_hub_articles(self) -> List[ResearchItem]:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        from services.agencies import match_agency

        client = BaseConnector.get_client()
        keywords = [
            "وزارة العمل",
            "وزير العمل",
            "molsa",
            "ministry of labour",
            "ministry of labor",
        ]
        hubs = list(dict.fromkeys([*ARTICLE_HUBS, *MINISTRY_LISTING_PAGES]))
        items: List[ResearchItem] = []

        async def scan(hub: str) -> List[ResearchItem]:
            found: List[ResearchItem] = []
            try:
                response = await asyncio.wait_for(client.get(hub), timeout=8)
                if response.status_code >= 400:
                    return found
                soup = BeautifulSoup(response.text, "html.parser")
                seen: set[str] = set()
                for anchor in soup.find_all("a", href=True):
                    text = " ".join(anchor.get_text(" ", strip=True).split())
                    href = urljoin(str(response.url), anchor["href"])
                    hay = f"{text} {href}".lower()
                    if not any(keyword in hay for keyword in keywords):
                        continue
                    if is_homepage_url(href):
                        continue
                    if href in seen or href.rstrip("/") == hub.rstrip("/"):
                        continue
                    seen.add(href)
                    agency = match_agency(href)
                    payload = {
                        "title": text or "Untitled",
                        "url": href,
                        "snippet": text,
                        "source": "agencies" if agency else "news",
                        "content": text,
                        "content_type": "news",
                        "status": "pending",
                    }
                    if agency:
                        payload["platform"] = agency.id
                        payload["agency_label"] = agency.label_ar
                        payload["metadata"] = {
                            "agency_id": agency.id,
                            "agency_label": agency.label_ar,
                            "platform": agency.label_ar,
                        }
                    found.append(BaseConnector.to_item(BaseConnector(), payload))
                    if len(found) >= 6:
                        break
            except Exception as exc:
                logger.debug("Hub scan failed for %s: %s", hub, exc)
            return found

        batches = await asyncio.gather(
            *[scan(hub) for hub in hubs],
            return_exceptions=True,
        )
        for batch in batches:
            if isinstance(batch, list):
                items.extend(batch)
        logger.info("Hub discovery found %s ministry-linked articles", len(items))
        return items

    async def _enrich_articles(
        self, items: List[ResearchItem], max_results: int
    ) -> List[ResearchItem]:
        social: List[ResearchItem] = []
        candidates: List[ResearchItem] = []
        for item in items:
            source = (item.source or "").lower()
            if source in SOCIAL_SOURCES or should_skip_html_fetch(item.url or ""):
                item.metadata.setdefault("post_kind", "post")
                item.metadata["status"] = "partial"
                social.append(item)
                continue
            candidates.append(item)

        candidates.sort(
            key=lambda item: (
                0 if is_official_domain(item.url) else 1,
                0 if is_trusted_news_domain(item.url) else 1,
            )
        )
        fetch_cap = min(32, max(max_results * 3, 12))
        to_fetch = candidates[:fetch_cap]
        leftover = candidates[fetch_cap:]

        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch_one(item: ResearchItem) -> ResearchItem:
            async with sem:
                return await self._fetch_and_extract(item) or item

        fetched: List[ResearchItem] = []
        try:
            batches = await asyncio.wait_for(
                asyncio.gather(
                    *[fetch_one(item) for item in to_fetch],
                    return_exceptions=True,
                ),
                timeout=FETCH_GLOBAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Article fetch timed out after %ss", FETCH_GLOBAL_TIMEOUT)
            batches = to_fetch

        for original, result in zip(to_fetch, batches):
            if isinstance(result, ResearchItem):
                fetched.append(result)
            else:
                original.metadata.setdefault("status", "partial")
                if isinstance(result, Exception):
                    original.metadata["fetch_error"] = str(result)
                fetched.append(original)

        kept: List[ResearchItem] = []
        for item in fetched:
            if self._is_listing_page(item):
                continue
            body = (item.content or "").strip()
            if body:
                item.description = make_excerpt(body) or item.description
            if not self._is_rich_enough(item):
                item.metadata["status"] = item.metadata.get("status") or "partial"
            kept.append(item)

        for item in leftover:
            if item in kept or self._is_listing_page(item):
                continue
            item.metadata.setdefault("status", "partial")
            kept.append(item)

        logger.info(
            "Enriched %s pages; kept %s articles (+ %s social mentions)",
            len(fetched),
            len(kept),
            len(social),
        )
        return kept + social

    async def _fetch_and_extract(self, item: ResearchItem) -> ResearchItem | None:
        url = item.url or ""
        if not url or should_skip_html_fetch(url):
            item.metadata.setdefault("status", "partial")
            return item
        try:
            client = BaseConnector.get_client()
            response = await asyncio.wait_for(client.get(url), timeout=FETCH_PAGE_TIMEOUT)
            if response.status_code >= 400:
                item.metadata["status"] = "partial"
                item.metadata["fetch_error"] = f"http_{response.status_code}"
                return item
            html = response.text or ""
            if self._looks_like_login_wall(html, str(response.url)):
                item.metadata["status"] = "partial"
                item.metadata["fetch_error"] = "login_wall"
                return item

            extracted = await asyncio.to_thread(
                extract_from_html, html, str(response.url or url)
            )
            body = (extracted.get("content") or "").strip()
            title = (extracted.get("title") or "").strip()
            meta = extracted.get("meta") or {}
            if title and (not item.title or item.title == "Untitled" or len(title) > 8):
                item.title = title
            if body:
                item.content = body
                item.description = make_excerpt(body)
                item.metadata["status"] = "ok"
                item.metadata["extraction"] = "article"
            if meta.get("author") and not item.author:
                item.author = str(meta["author"])
            if meta.get("date") and not item.published_date:
                item.published_date = self._parse_loose_date(meta["date"])
            if meta.get("image") and not item.image:
                item.image = meta["image"]
            if response.url:
                item.url = str(response.url)
            return item
        except Exception as exc:
            logger.debug("Could not extract %s: %s", url, exc)
            item.metadata["status"] = "partial"
            item.metadata["fetch_error"] = str(exc)
            return item

    def _looks_like_login_wall(self, html: str, url: str) -> bool:
        url_l = (url or "").lower()
        if any(part in url_l for part in ("/login", "/signin", "/sign-in", "accounts.")):
            return True
        text = html or ""
        if len(text) > 12000:
            return False
        head = text[:1500].lower()
        return ("password" in head and "login" in head) or (
            "type=\"password\"" in head and len(text) < 5000
        )

    def _is_listing_page(self, item: ResearchItem) -> bool:
        title = (item.title or "").strip()
        generic_titles = {
            "أهم الأخبار",
            "اخبار",
            "أخبار",
            "news",
            "home",
            "الرئيسية",
            "latest news",
        }
        if title.lower() in generic_titles:
            return True
        if is_homepage_url(item.url or ""):
            return True
        url = (item.url or "").rstrip("/")
        for hub in ARTICLE_HUBS:
            if url == hub.rstrip("/"):
                return True
        return False

    def _is_rich_enough(self, item: ResearchItem) -> bool:
        if (item.source or "").lower() in SOCIAL_SOURCES:
            return True
        if is_official_domain(item.url or ""):
            return True
        return len((item.content or "").strip()) >= MIN_BODY_CHARS

    def _parse_loose_date(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def _publish_partial(self, task: Dict[str, Any], items: List[ResearchItem]) -> None:
        try:
            serialized = [self._serialize_item(item) for item in items if item.is_valid]
            task["results"] = serialized
            task_id = task.get("id")
            if task_id:
                self.results_storage[task_id] = serialized
        except Exception:
            logger.debug("Could not publish partial results", exc_info=True)

    async def _clean_results(self, results: List[ResearchItem]) -> List[ResearchItem]:
        cleaned = []
        for item in results:
            try:
                if item.content:
                    try:
                        item.content = await self.cleaner.clean_html(item.content)
                    except Exception:
                        pass
                elif item.description:
                    item.content = item.description

                try:
                    parsed = await self.parser.parse(item)
                    if isinstance(parsed, dict):
                        item.metadata.update(parsed)
                except Exception:
                    pass

                cleaned.append(item)
            except Exception as e:
                logger.error("Error cleaning item %s: %s", getattr(item, "title", "?"), e)
                cleaned.append(item)

        logger.info("Cleaned %s items from %s total", len(cleaned), len(results))
        return cleaned

    def _remove_duplicates(
        self,
        results: List[ResearchItem],
        seen_urls: Set[str],
        seen_titles: Set[str],
    ) -> List[ResearchItem]:
        deduped = []
        for item in results:
            canonical = canonicalize_url(item.url or "") or item.url
            if canonical in seen_urls or item.url in seen_urls:
                continue
            normalized_title = " ".join((item.title or "").lower().split())
            if normalized_title and normalized_title in seen_titles:
                continue
            seen_urls.add(canonical)
            if item.url:
                seen_urls.add(item.url)
            if normalized_title:
                seen_titles.add(normalized_title)
            deduped.append(item)

        removed = len(results) - len(deduped)
        logger.info("Removed %s duplicates, %s items remaining", removed, len(deduped))
        return deduped

    def _filter_by_date(
        self,
        results: List[ResearchItem],
        date_from: str | None,
        date_to: str | None,
        topic: str | None = None,
    ) -> List[ResearchItem]:
        if not date_from and not date_to:
            return results

        start = None
        end = None
        try:
            if date_from:
                start = datetime.fromisoformat(date_from).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            if date_to:
                end = datetime.fromisoformat(date_to).replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
        except ValueError:
            logger.warning("Invalid date filter values: %s - %s", date_from, date_to)
            return results

        ministry = is_ministry_topic(topic or "")
        filtered = []
        for item in results:
            if not item.published_date:
                if ministry and not has_ministry_entity(item):
                    continue
                filtered.append(item)
                continue
            item_date = item.published_date
            if item_date.tzinfo is not None:
                item_date = item_date.replace(tzinfo=None)
            if start and item_date < start:
                continue
            if end and item_date > end:
                continue
            filtered.append(item)

        logger.info(
            "Date filter kept %s of %s items (%s → %s)",
            len(filtered),
            len(results),
            date_from,
            date_to,
        )
        return filtered

    def _filter_by_content_type(
        self, results: List[ResearchItem], content_type: str
    ) -> List[ResearchItem]:
        content_type = (content_type or "all").lower()
        if content_type in {"", "all"}:
            return results

        social_sources = SOCIAL_SOURCES
        filtered = []
        for item in results:
            item_type = getattr(item.content_type, "value", item.content_type)
            item_type = (item_type or "").lower()
            source = (item.source or "").lower()

            if content_type == "social":
                if item_type in {"social", "forum"} or source in social_sources:
                    filtered.append(item)
            elif content_type == "forum":
                if item_type == "forum" or source == "reddit":
                    filtered.append(item)
            elif content_type == "agencies":
                meta = item.metadata or {}
                if source == "agencies" or meta.get("agency_id") or item_type == "news":
                    filtered.append(item)
            elif content_type == "news":
                if item_type in {"news", "rss"} or source in {"news", "rss", "google", "bing"}:
                    filtered.append(item)
            else:
                if item_type == content_type:
                    filtered.append(item)

        return filtered

    def _sort_by_date(self, results: List[ResearchItem]) -> List[ResearchItem]:
        def get_date(item: ResearchItem) -> datetime:
            if item.published_date:
                return item.published_date
            return item.scraped_at

        return sorted(results, key=get_date, reverse=True)

    def _rank_results(
        self, results: List[ResearchItem], topic: str, province: str | None = None
    ) -> List[ResearchItem]:
        kind_rank = {
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
        location = [term.lower() for term in province_terms(province)]
        semantic = (
            similarity_scores(topic, results) if is_ministry_topic(topic) else [0.0] * len(results)
        )
        lexical_bm25 = bm25_scores(topic, results) if is_ministry_topic(topic) else [0.0] * len(results)
        semantic_by_id = {id(item): score for item, score in zip(results, semantic)}
        bm25_by_id = {id(item): score for item, score in zip(results, lexical_bm25)}

        def rank_key(item: ResearchItem) -> tuple:
            date = item.published_date or item.scraped_at
            stamp = date.timestamp() if date else 0
            official = 0 if is_official_domain(item.url or "") else 1
            trusted = 0 if is_trusted_news_domain(item.url or "") or is_trusted_item(item) else 1
            social_last = 1 if (item.source or "").lower() in EXPLORATORY_SOCIAL else 0
            body_len = len((item.content or "").strip())
            thin = 0 if body_len >= MIN_BODY_CHARS else 1
            lexical = ministry_relevance_score(item) if is_ministry_topic(topic) else 0
            score = -(
                lexical
                + 4.0 * bm25_by_id.get(id(item), 0.0)
                + 10.0 * semantic_by_id.get(id(item), 0.0)
            )
            kind = (item.metadata or {}).get("post_kind") or ""
            social_kind = kind_rank.get(kind, 6)
            hay = f"{item.title or ''} {item.content or ''} {item.description or ''}".lower()
            local = 0 if location and any(term in hay for term in location) else 1
            return (social_last, thin, official, trusted, local, social_kind, score, -stamp)

        ranked = sorted(results, key=rank_key)
        if is_ministry_topic(topic):
            return ranked[:MINISTRY_RESULT_CAP]
        return ranked

    def _serialize_item(self, item: ResearchItem) -> dict:
        data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
        for key in ("published_date", "scraped_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        if hasattr(data.get("content_type"), "value"):
            data["content_type"] = data["content_type"].value
        if hasattr(data.get("language"), "value"):
            data["language"] = data["language"].value
        # Surface hashtags/mentions on cards even if keywords was empty
        meta = data.get("metadata") or {}
        tags = list(data.get("keywords") or [])
        for key in ("hashtags", "mentions"):
            for value in meta.get(key) or []:
                if value not in tags:
                    tags.append(value)
        data["keywords"] = tags
        body = data.get("content") or ""
        data["excerpt"] = make_excerpt(body) or data.get("description") or ""
        data["is_official"] = is_official_domain(data.get("url") or "") or bool(meta.get("official"))
        data["is_social_mention"] = (data.get("source") or "").lower() in SOCIAL_SOURCES
        data["is_exploratory"] = (data.get("source") or "").lower() in EXPLORATORY_SOCIAL
        data["post_kind"] = meta.get("post_kind") or ""
        data["agency_label"] = meta.get("agency_label") or ""
        data["platform"] = meta.get("platform") or data.get("source") or ""
        data["provenance"] = meta.get("provenance") or item_provenance(item)
        return data

    async def get_results(self, task_id: str) -> Dict[str, Any]:
        """Get results for a task."""
        if task_id in self.results_storage:
            task = self.active_tasks.get(task_id, {})
            return {
                "task_id": task_id,
                "status": task.get("status", "completed"),
                "results": self.results_storage[task_id],
                "stats": self._stats_payload(task.get("stats")),
                "error": task.get("error"),
                "message": task.get("message"),
                "date_filter_relaxed": task.get("date_filter_relaxed", False),
                "semantic": task.get("semantic") or semantic_status(),
            }

        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            return {
                "task_id": task_id,
                "status": task["status"],
                "results": task.get("results", []),
                "stats": self._stats_payload(task.get("stats")),
                "error": task.get("error"),
                "message": task.get("message"),
                "date_filter_relaxed": task.get("date_filter_relaxed", False),
                "semantic": task.get("semantic") or semantic_status(),
            }

        return {"error": f"Task {task_id} not found", "status": "error", "results": [], "semantic": semantic_status()}

    def _stats_payload(self, stats: Any) -> dict | None:
        if stats is None:
            return None
        if isinstance(stats, dict):
            return stats
        return {
            "connectors_used": getattr(stats, "connectors_used", []),
            "pages_crawled": getattr(stats, "pages_crawled", 0),
            "items_processed": getattr(stats, "items_processed", 0),
            "duplicates_found": getattr(stats, "duplicates_found", 0),
            "errors": getattr(stats, "errors", 0),
            "execution_time": getattr(stats, "execution_time", 0),
        }
