import os

import pytest
from types import SimpleNamespace

from services.semantic import semantic_status, similarity_scores


def test_similarity_scores_zero_when_disabled(monkeypatch):
    monkeypatch.setattr("services.semantic._enabled", lambda: False)
    items = [SimpleNamespace(title="وزارة العمل", description="خبر", content="")]
    assert similarity_scores("وزارة العمل", items) == [0.0]


def test_semantic_status_off_when_disabled(monkeypatch):
    monkeypatch.setattr("services.semantic._enabled", lambda: False)
    assert semantic_status() == "off"


def test_similarity_scores_encodes_article_body(monkeypatch):
    seen = []

    class FakeModel:
        def encode(self, texts, **kwargs):
            seen.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("services.semantic._enabled", lambda: True)
    monkeypatch.setattr("services.semantic._load_model", lambda: FakeModel())
    items = [
        SimpleNamespace(
            title="عنوان",
            description="مقتطف",
            content="أعلنت وزارة العمل والشؤون الاجتماعية عن قرارات جديدة في بغداد " * 3,
            metadata={},
        )
    ]
    scores = similarity_scores("وزارة العمل", items)
    assert scores == [1.0]
    assert "وزارة العمل والشؤون الاجتماعية" in seen[1]


def test_similarity_scores_cosine(monkeypatch):
    class FakeModel:
        def encode(self, texts, **kwargs):
            mapping = {
                "وزارة العمل": [1.0, 0.0],
                "وزارة العمل خبر عاجل": [0.8, 0.6],
                " unrelated sports": [0.0, 1.0],
            }
            rows = []
            for text in texts:
                rows.append(mapping.get(text, [0.0, 1.0]))
            return rows

    monkeypatch.setattr("services.semantic._enabled", lambda: True)
    monkeypatch.setattr("services.semantic._load_model", lambda: FakeModel())
    items = [
        SimpleNamespace(title="وزارة العمل", description="خبر عاجل", content=""),
        SimpleNamespace(title=" unrelated sports", description="", content=""),
    ]
    scores = similarity_scores("وزارة العمل", items)
    assert scores[0] > scores[1]
    assert 0.0 <= scores[1] <= scores[0] <= 1.0


@pytest.mark.skipif(os.environ.get("RUN_SEMANTIC_MODEL") != "1", reason="offline CI skips HF download")
def test_real_zarra_model_orders_arabic(monkeypatch):
    import services.semantic as semantic

    monkeypatch.setattr("services.semantic._enabled", lambda: True)
    semantic._failed = False
    semantic._model = None
    semantic._load_attempts = 0
    items = [
        SimpleNamespace(title="وزارة العمل تعلن قرارات", description="وزارة العمل والشؤون الاجتماعية", content="", metadata={}),
        SimpleNamespace(title="نتائج مباراة كرة القدم", description=" spor ts", content="", metadata={}),
    ]
    scores = similarity_scores("وزارة العمل والشؤون الاجتماعية", items)
    assert scores[0] > scores[1]

