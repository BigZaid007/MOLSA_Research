#!/usr/bin/env python3
"""Run MOLSA golden queries twice and print trusted/dated/entity/stability gates.

Usage (from repo root, with app on PYTHONPATH):

    cd app && python ../scripts/golden_search.py
    cd app && python ../scripts/golden_search.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _offline_fixture() -> list[dict]:
    return [
        {
            "title": "وزارة العمل تعلن عن فرص عمل",
            "url": "https://www.ina.iq/story/1",
            "source": "agencies",
            "published_date": "2026-09-07T10:00:00",
            "description": "وزارة العمل والشؤون الاجتماعية",
            "content": "وزارة العمل والشؤون الاجتماعية تعلن",
            "metadata": {"agency_id": "ina", "provenance": "verified"},
        },
        {
            "title": "وزير العمل يصدر قرارا",
            "url": "https://www.ninanews.com/story/2",
            "source": "rss",
            "published_date": "2026-09-06T10:00:00",
            "description": "وزير العمل العراقي",
            "content": "وزير العمل",
            "metadata": {"provenance": "verified"},
        },
        {
            "title": "وزارة العمل على تيليغرام",
            "url": "https://t.me/molsa2023/99",
            "source": "telegram",
            "published_date": "2026-09-07T08:00:00",
            "description": "وزارة العمل والشؤون الاجتماعية",
            "content": "وزارة العمل",
            "metadata": {"official": True, "provenance": "verified"},
        },
    ]


async def _live_search(topic: str, max_results: int = 10) -> tuple[list[dict], str]:
    from config.settings import get_settings
    from services.processor import ResearchProcessor, resolve_sources
    from services.semantic import semantic_status

    processor = ResearchProcessor()
    sources = resolve_sources("all", None)
    task_id = await processor.process_research(
        topic=topic,
        sources=sources,
        max_results=max_results,
        settings=get_settings(),
        content_type="all",
    )
    await processor.start_processing(task_id)
    payload = await processor.get_results(task_id)
    return list(payload.get("results") or []), payload.get("semantic") or semantic_status()


async def _run(live: bool, max_results: int, queries: list[str] | None = None) -> dict:
    from services.quality_gate import GOLDEN_QUERIES, evaluate_pair, summarize_runs
    from services.semantic import semantic_status

    reports = []
    status = semantic_status()
    topics = queries or list(GOLDEN_QUERIES)
    for topic in topics:
        if live:
            first, status = await _live_search(topic, max_results=max_results)
            second, status = await _live_search(topic, max_results=max_results)
        else:
            first = _offline_fixture()
            second = list(_offline_fixture())
            status = "ready"
        reports.append(evaluate_pair(first, second, topic, semantic_status=status))
    return summarize_runs(reports)


def main() -> int:
    parser = argparse.ArgumentParser(description="MOLSA golden-query quality gate")
    parser.add_argument("--live", action="store_true", help="Hit live connectors (slow, network)")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--query", action="append", dest="queries", help="Override golden queries (repeatable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    summary = asyncio.run(_run(live=args.live, max_results=args.max_results, queries=args.queries))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
