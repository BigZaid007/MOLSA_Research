"""CPU-only Arabic reranker for 1GB droplets.

Uses NAMAA Zarra int8 (Model2Vec): static token embeddings, no PyTorch.
Falls back to zeros if the model cannot load so search still works.
"""

from __future__ import annotations

import inspect
import logging
import os
import threading
from typing import Any, Sequence

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "NAMAA-Space/zarra_int8"
_MAX_TITLE_CHARS = 180
_MAX_SNIPPET_CHARS = 360
_MAX_BODY_CHARS = 800
_lock = threading.Lock()
_model: Any = None
_failed = False
_load_attempts = 0
_MAX_LOAD_ATTEMPTS = 3
_warmup_started = False
_warmup_done = threading.Event()


def _enabled() -> bool:
    return os.environ.get("SEMANTIC_RERANK", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def semantic_status() -> str:
    if not _enabled():
        return "off"
    if _model is not None:
        return "ready"
    if _failed:
        return "off"
    return "loading"


def _encode_kwargs() -> dict[str, Any]:
    return {
        "show_progress_bar": False,
        "use_multiprocessing": False,
        "batch_size": 32,
    }


def _encode(model: Any, texts: list[str]):
    kwargs = _encode_kwargs()
    try:
        accepted = inspect.signature(model.encode).parameters
        kwargs = {key: value for key, value in kwargs.items() if key in accepted}
    except (TypeError, ValueError):
        pass
    return model.encode(texts, **kwargs)


def _load_model():
    global _model, _failed, _load_attempts
    if not _enabled():
        _warmup_done.set()
        return None
    if _model is not None or _failed:
        _warmup_done.set()
        return _model
    with _lock:
        if _model is not None or _failed:
            _warmup_done.set()
            return _model
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        _load_attempts += 1
        try:
            from model2vec import StaticModel

            name = os.environ.get("SEMANTIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
            logger.info("Loading semantic ranker %s", name)
            load_kwargs = {"force_download": False}
            try:
                accepted = inspect.signature(StaticModel.from_pretrained).parameters
                load_kwargs = {
                    key: value for key, value in load_kwargs.items() if key in accepted
                }
            except (TypeError, ValueError):
                load_kwargs = {}
            _model = StaticModel.from_pretrained(name, **load_kwargs)
            logger.info("Semantic ranker ready")
        except Exception as exc:
            _model = None
            if _load_attempts >= _MAX_LOAD_ATTEMPTS:
                _failed = True
            logger.warning("Semantic ranker unavailable (%s); using keyword ranking only", exc)
        finally:
            _warmup_done.set()
        return _model


def warmup_semantic_ranker() -> None:
    """Download/load the model in the background so the first search is not stalled."""
    global _warmup_started
    if _warmup_started or not _enabled():
        if not _enabled():
            _warmup_done.set()
        return
    _warmup_started = True
    threading.Thread(target=_load_model, name="semantic-warmup", daemon=True).start()


def wait_for_semantic_ranker(timeout: float = 8.0) -> str:
    """Best-effort wait so ranking does not silently flip mid-session."""
    if not _enabled():
        return "off"
    if _model is not None or _failed:
        return semantic_status()
    warmup_semantic_ranker()
    _warmup_done.wait(timeout=timeout)
    return semantic_status()


def _doc_text(item: Any) -> str:
    title = (getattr(item, "title", None) or "")[:_MAX_TITLE_CHARS]
    snippet = (getattr(item, "description", None) or "")[:_MAX_SNIPPET_CHARS]
    body = (getattr(item, "content", None) or "")[:_MAX_BODY_CHARS]
    if body and body.strip() == snippet.strip():
        body = ""
    return " ".join(part for part in (title, snippet, body) if part).strip() or title


def similarity_scores(topic: str, items: Sequence[Any]) -> list[float]:
    """Return cosine similarity in [0, 1] for each item, or zeros if unavailable."""
    count = len(items)
    if count == 0 or not (topic or "").strip():
        return [0.0] * count
    cached = []
    missing = False
    for item in items:
        meta = getattr(item, "metadata", None) or {}
        if isinstance(meta, dict) and "semantic_score" in meta:
            cached.append(float(meta["semantic_score"]))
        else:
            missing = True
            break
    if not missing and cached:
        return cached
    model = _load_model()
    if model is None:
        return [0.0] * count
    try:
        import numpy as np

        query = np.asarray(_encode(model, [topic]), dtype=np.float32)
        docs = np.asarray(_encode(model, [_doc_text(item) for item in items]), dtype=np.float32)
        if query.ndim == 2:
            query = query[0]
        if docs.ndim == 1:
            docs = docs.reshape(1, -1)
        query_norm = float(np.linalg.norm(query)) or 1.0
        doc_norm = np.linalg.norm(docs, axis=1)
        doc_norm = np.maximum(doc_norm, 1e-8)
        sims = (docs @ query) / (doc_norm * query_norm)
        scores = [float(max(0.0, min(1.0, score))) for score in sims]
        for item, score in zip(items, scores):
            meta = getattr(item, "metadata", None)
            if isinstance(meta, dict):
                meta["semantic_score"] = score
        return scores
    except Exception as exc:
        logger.warning("Semantic scoring failed: %s", exc)
        return [0.0] * count
