"""Golden-query quality gates for MOLSA search (trusted / dated / entity / stability)."""

from __future__ import annotations

from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from services.focus import (
    MINISTRY_DOMAINS,
    TRUSTED_NEWS_DOMAINS,
    has_ministry_entity_phrase,
    is_ministry_topic,
    is_official_domain,
    is_trusted_news_domain,
)

GOLDEN_QUERIES = (
    "وزارة العمل والشؤون الاجتماعية",
    "وزير العمل قرارات",
    "الحماية الاجتماعية الراتب",
    "البطالة البصرة",
    "MOLSA Iraq Ministry of Labour",
)

TRUSTED_SHARE_MIN = 0.40
DATED_SHARE_MIN = 0.50
ENTITY_SHARE_MIN = 1.0
TRUSTED_JACCARD_MIN = 0.50

TRUSTED_SOURCES = {"rss", "news", "agencies", "telegram"}
EXPLORATORY_SOCIAL = {"facebook", "instagram", "linkedin", "x", "tiktok", "reddit"}


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        meta = item.get("metadata") or {}
        if key in item:
            return item.get(key, default)
        return meta.get(key, default)
    meta = getattr(item, "metadata", None) or {}
    if hasattr(item, key):
        return getattr(item, key, default)
    return meta.get(key, default)


def _url(item: Any) -> str:
    return (_item_get(item, "url") or "").strip()


def _source(item: Any) -> str:
    return (_item_get(item, "source") or "").lower()


def _domain(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def is_trusted_hit(item: Any) -> bool:
    url = _url(item)
    source = _source(item)
    meta = _item_get(item, "metadata") if isinstance(_item_get(item, "metadata"), dict) else {}
    if isinstance(item, dict):
        meta = item.get("metadata") or {}
    else:
        meta = getattr(item, "metadata", None) or {}
    if source in TRUSTED_SOURCES or meta.get("agency_id"):
        return True
    if meta.get("official") and source == "telegram":
        return True
    if is_official_domain(url) or is_trusted_news_domain(url):
        return True
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in MINISTRY_DOMAINS + TRUSTED_NEWS_DOMAINS)


def _haystack(item: Any) -> str:
    return " ".join(
        [
            str(_item_get(item, "title") or ""),
            str(_item_get(item, "description") or ""),
            str(_item_get(item, "content") or "")[:800],
        ]
    )


def names_ministry(item: Any) -> bool:
    return has_ministry_entity_phrase(_haystack(item))


def evaluate_results(results: Sequence[Any], topic: str) -> dict[str, Any]:
    items = list(results or [])
    total = len(items)
    trusted = [item for item in items if is_trusted_hit(item)]
    dated = [item for item in items if _item_get(item, "published_date")]
    entity = [item for item in items if names_ministry(item)]
    trusted_share = (len(trusted) / total) if total else 0.0
    dated_share = (len(dated) / total) if total else 0.0
    entity_share = (len(entity) / total) if total else 1.0
    ministry = is_ministry_topic(topic)
    return {
        "topic": topic,
        "count": total,
        "trusted_count": len(trusted),
        "dated_count": len(dated),
        "entity_count": len(entity),
        "trusted_share": trusted_share,
        "dated_share": dated_share,
        "entity_share": entity_share,
        "trusted_urls": [_url(item) for item in trusted if _url(item)],
        "gates": {
            "trusted": trusted_share >= TRUSTED_SHARE_MIN if total else False,
            "dated": dated_share >= DATED_SHARE_MIN if total else False,
            "entity": (not ministry) or entity_share >= ENTITY_SHARE_MIN,
        },
    }


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = {url for url in left if url}
    b = {url for url in right if url}
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def evaluate_pair(
    first: Sequence[Any],
    second: Sequence[Any],
    topic: str,
    semantic_status: str = "off",
) -> dict[str, Any]:
    run_a = evaluate_results(first, topic)
    run_b = evaluate_results(second, topic)
    overlap = jaccard(run_a["trusted_urls"], run_b["trusted_urls"])
    gates = {
        "trusted": run_a["gates"]["trusted"] and run_b["gates"]["trusted"],
        "dated": run_a["gates"]["dated"] and run_b["gates"]["dated"],
        "entity": run_a["gates"]["entity"] and run_b["gates"]["entity"],
        "stability": overlap >= TRUSTED_JACCARD_MIN,
        "semantic": semantic_status == "ready",
    }
    return {
        "topic": topic,
        "run_a": run_a,
        "run_b": run_b,
        "trusted_jaccard": overlap,
        "semantic_status": semantic_status,
        "gates": gates,
        "passed": all(gates.values()),
    }


def summarize_runs(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    passed = [report for report in reports if report.get("passed")]
    return {
        "queries": len(reports),
        "passed": len(passed),
        "failed": len(reports) - len(passed),
        "ok": bool(reports) and len(passed) == len(reports),
        "reports": list(reports),
    }
