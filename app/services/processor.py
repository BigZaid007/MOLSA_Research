import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Set

SOURCE_TIMEOUT_SECONDS = 16
GLOBAL_TIMEOUT_SECONDS = 22
SOCIAL_SOURCE_TIMEOUT_SECONDS = 22
SOCIAL_GLOBAL_TIMEOUT_SECONDS = 36
FETCH_PAGE_TIMEOUT = 8
FETCH_CONCURRENCY = 8
FETCH_GLOBAL_TIMEOUT = 35
SOCIAL_SOURCES = {"facebook", "instagram", "linkedin", "x", "tiktok", "reddit", "telegram"}
WEB_SOURCES = {"google", "bing", "rss", "news"}

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
    MINISTRY_SEED_PAGES,
    MINISTRY_POSITIVE,
    build_search_queries,
    filter_ministry_results,
    is_ministry_topic,
    province_terms,
    is_official_domain,
    is_trusted_news_domain,
    ministry_relevance_score,
    should_skip_html_fetch,
)
from services.quality import filter_research_items

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
            "status": "pending",
            "start_time": datetime.now(),
            "settings": settings,
            "results": [],
            "stats": None,
            "error": None,
            "message": None,
            "date_filter_relaxed": False,
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

            sources = list(task["sources"] or [])
            content_type = (task.get("content_type") or "all").lower()
            if content_type == "social":
                sources = [s for s in sources if s in SOCIAL_SOURCES] or list(SOCIAL_SOURCES)
            else:
                sources = [s for s in sources if s in WEB_SOURCES] or list(WEB_SOURCES)

            collected: List[ResearchItem] = []

            query_limit = 3 if content_type == "social" else 2
            source_timeout = (
                SOCIAL_SOURCE_TIMEOUT_SECONDS if content_type == "social" else SOURCE_TIMEOUT_SECONDS
            )
            global_timeout = (
                SOCIAL_GLOBAL_TIMEOUT_SECONDS if content_type == "social" else GLOBAL_TIMEOUT_SECONDS
            )

            async def run_source(source: str) -> List[ResearchItem]:
                logger.info("Processing source: %s", source)
                source_queries = queries[:query_limit] if queries else [topic]
                bucket: List[ResearchItem] = []
                for query in source_queries:
                    batch = await self._process_source(
                        query, source, task["max_results"]
                    )
                    bucket.extend(batch)
                    if len(bucket) >= task["max_results"]:
                        break
                return bucket[: task["max_results"] * 2]

            async def run_source_safe(source: str) -> List[ResearchItem]:
                try:
                    batch = await asyncio.wait_for(run_source(source), source_timeout)
                    collected.extend(batch)
                    self._publish_partial(task, collected)
                    return batch
                except Exception as exc:
                    logger.error("Error processing source %s: %s", source, exc)
                    return []

            hub_task = None
            if content_type != "social" and is_ministry_topic(topic):
                hub_task = asyncio.create_task(self._discover_hub_articles())

            try:
                batches = await asyncio.wait_for(
                    asyncio.gather(
                        *[run_source_safe(source) for source in sources],
                        return_exceptions=True,
                    ),
                    timeout=global_timeout,
                )
                for batch in batches:
                    if isinstance(batch, Exception):
                        errors += 1
            except asyncio.TimeoutError:
                logger.warning("Global search timeout for %s; returning partial results", task_id)
                errors += 1

            all_results = collected
            if content_type != "social" and is_ministry_topic(topic):
                official_hits = [item for item in all_results if is_official_domain(item.url or "")]
                if len(official_hits) < 3:
                    all_results.extend(self._official_seed_items())
                if hub_task is not None:
                    try:
                        all_results.extend(await asyncio.wait_for(hub_task, timeout=8))
                    except Exception as exc:
                        logger.debug("Hub discovery skipped: %s", exc)
                        hub_task.cancel()
            if content_type == "social":
                for item in all_results:
                    item.metadata.setdefault("post_kind", "post")
                    item.metadata["status"] = "partial"
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
            )

            message = None
            date_filter_relaxed = False
            # If the date window wiped everything, show closest matches instead of empty
            if (
                not filtered_results
                and before_date
                and (task.get("date_from") or task.get("date_to"))
            ):
                filtered_results = before_date
                date_filter_relaxed = True
                message = (
                    "No ministry results were found inside your selected date range. "
                    "Showing the closest matching results outside that range instead."
                )
                logger.info("Date filter relaxed for task %s", task_id)

            typed_results = self._filter_by_content_type(filtered_results, content_type)
            sorted_results = self._rank_results(typed_results, topic, task.get("province"))
            serialized = [self._serialize_item(item) for item in sorted_results]

            task["results"] = serialized
            task["status"] = "completed"
            task["message"] = message
            task["date_filter_relaxed"] = date_filter_relaxed
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
        self, topic: str, source: str, max_results: int
    ) -> List[ResearchItem]:
        connector = get_connector(source)
        if not connector:
            logger.warning("No connector registered for source: %s", source)
            return []

        if hasattr(connector, "is_available") and not await connector.is_available():
            logger.warning("Connector %s is not available", source)
            return []

        search_results = await connector.search(topic) or []
        search_results = search_results[: max(max_results, 12)]

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

    async def _discover_hub_articles(self) -> List[ResearchItem]:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        client = BaseConnector.get_client()
        keywords = [signal.lower() for signal in MINISTRY_POSITIVE[:8]]
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
                    if href in seen or href.rstrip("/") == hub.rstrip("/"):
                        continue
                    seen.add(href)
                    found.append(
                        BaseConnector.to_item(
                            BaseConnector(),
                            {
                                "title": text or "Untitled",
                                "url": href,
                                "snippet": text,
                                "source": "news",
                                "content": text,
                                "content_type": "news",
                                "status": "pending",
                            },
                        )
                    )
                    if len(found) >= 6:
                        break
            except Exception as exc:
                logger.debug("Hub scan failed for %s: %s", hub, exc)
            return found

        batches = await asyncio.gather(
            *[scan(hub) for hub in ARTICLE_HUBS],
            return_exceptions=True,
        )
        for batch in batches:
            if isinstance(batch, list):
                items.extend(batch)
        logger.info("Hub discovery found %s ministry-linked articles", len(items))
        return items

    def _official_seed_items(self) -> List[ResearchItem]:
        items: List[ResearchItem] = []
        for seed in MINISTRY_SEED_PAGES:
            try:
                item = BaseConnector.to_item(
                    BaseConnector(),
                    {
                        **seed,
                        "content": seed.get("snippet"),
                        "status": "pending",
                        "content_type": "website",
                    },
                )
                if item.is_valid:
                    items.append(item)
            except Exception:
                continue
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

        async def fetch_one(item: ResearchItem) -> ResearchItem | None:
            async with sem:
                return await self._fetch_and_extract(item)

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

        for result in batches:
            if isinstance(result, ResearchItem):
                fetched.append(result)
            elif isinstance(result, Exception):
                logger.debug("Fetch task failed: %s", result)

        kept: List[ResearchItem] = []
        for item in fetched:
            if self._is_listing_page(item):
                continue
            if self._is_rich_enough(item):
                body = (item.content or "").strip()
                if body:
                    item.description = make_excerpt(body) or item.description
                kept.append(item)

        if len(kept) < 3:
            for item in fetched + leftover:
                if item in kept:
                    continue
                if is_official_domain(item.url) or (item.content or "").strip():
                    kept.append(item)
                if len(kept) >= max_results:
                    break

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
            return item if is_official_domain(url) else None
        try:
            client = BaseConnector.get_client()
            response = await asyncio.wait_for(client.get(url), timeout=FETCH_PAGE_TIMEOUT)
            if response.status_code >= 400:
                return item if is_official_domain(url) else None
            html = response.text or ""
            if self._looks_like_login_wall(html, str(response.url)):
                item.metadata["status"] = "partial"
                item.metadata["fetch_error"] = "login_wall"
                return item if is_official_domain(url) else None

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
            return item if is_official_domain(url) else None

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
            if item.url in seen_urls:
                continue
            normalized_title = item.title.lower().strip()
            if normalized_title in seen_titles:
                continue
            seen_urls.add(item.url)
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

        filtered = []
        for item in results:
            # Only filter on real publication dates. Unknown dates stay visible.
            if not item.published_date:
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
            elif content_type == "news":
                if item_type in {"news", "rss"} or source in {"news", "rss", "google", "bing"}:
                    filtered.append(item)
            else:
                if item_type == content_type:
                    filtered.append(item)

        return filtered or results

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

        def rank_key(item: ResearchItem) -> tuple:
            date = item.published_date or item.scraped_at
            stamp = date.timestamp() if date else 0
            official = 0 if is_official_domain(item.url or "") else 1
            trusted = 0 if is_trusted_news_domain(item.url or "") else 1
            body_len = len((item.content or "").strip())
            thin = 0 if body_len >= MIN_BODY_CHARS else 1
            score = -ministry_relevance_score(item) if is_ministry_topic(topic) else 0
            kind = (item.metadata or {}).get("post_kind") or ""
            social_kind = kind_rank.get(kind, 6)
            hay = f"{item.title or ''} {item.content or ''} {item.description or ''}".lower()
            local = 0 if location and any(term in hay for term in location) else 1
            return (thin, official, trusted, local, social_kind, score, -stamp)

        return sorted(results, key=rank_key)

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
        data["post_kind"] = meta.get("post_kind") or ""
        data["platform"] = meta.get("platform") or data.get("source") or ""
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
            }

        return {"error": f"Task {task_id} not found", "status": "error", "results": []}

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
