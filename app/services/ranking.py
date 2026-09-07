"""Hybrid BM25 lexical scores to blend with Zarra cosine ranking."""

from __future__ import annotations

import re
from typing import Any, Sequence

from services.arabic import normalize_arabic

_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_arabic(text))


def _doc_tokens(item: Any) -> list[str]:
    parts = [
        getattr(item, "title", None) or "",
        getattr(item, "description", None) or "",
        (getattr(item, "content", None) or "")[:800],
    ]
    return tokenize(" ".join(parts))


def bm25_scores(topic: str, items: Sequence[Any]) -> list[float]:
    """Return 0–1 BM25 ranks, or token-overlap fallback if rank-bm25 is missing."""
    count = len(items)
    if count == 0:
        return []
    query = tokenize(topic)
    corpus = [_doc_tokens(item) for item in items]
    if not query or not any(corpus):
        return [0.0] * count
    try:
        from rank_bm25 import BM25Okapi

        raw = BM25Okapi(corpus).get_scores(query)
        peak = max(float(score) for score in raw) or 1.0
        return [max(0.0, min(1.0, float(score) / peak)) for score in raw]
    except Exception:
        qset = set(query)
        scores = []
        for tokens in corpus:
            if not tokens:
                scores.append(0.0)
                continue
            overlap = len(qset.intersection(tokens))
            scores.append(overlap / max(len(qset), 1))
        return scores
