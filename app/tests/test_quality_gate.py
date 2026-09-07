from services.quality_gate import (
    GOLDEN_QUERIES,
    evaluate_pair,
    evaluate_results,
    jaccard,
)


def _trusted_item(url="https://www.ina.iq/1"):
    return {
        "title": "وزارة العمل تعلن",
        "url": url,
        "source": "agencies",
        "published_date": "2026-09-07",
        "description": "وزارة العمل والشؤون الاجتماعية",
        "content": "وزارة العمل والشؤون الاجتماعية",
        "metadata": {"agency_id": "ina", "provenance": "verified"},
    }


def test_golden_queries_are_defined():
    assert len(GOLDEN_QUERIES) >= 5


def test_trusted_dated_entity_gates_pass_on_agency_hits():
    items = [
        _trusted_item("https://www.ina.iq/1"),
        _trusted_item("https://www.ninanews.com/2"),
        {
            "title": "وزارة العمل على تيليغرام",
            "url": "https://t.me/molsa2023/1",
            "source": "telegram",
            "published_date": "2026-09-07",
            "description": "وزارة العمل",
            "metadata": {"official": True},
        },
    ]
    report = evaluate_results(items, "وزارة العمل والشؤون الاجتماعية")
    assert report["gates"]["trusted"]
    assert report["gates"]["dated"]
    assert report["gates"]["entity"]


def test_pair_stability_on_same_trusted_urls():
    first = [_trusted_item("https://www.ina.iq/1"), _trusted_item("https://www.ina.iq/2")]
    second = [_trusted_item("https://www.ina.iq/2"), _trusted_item("https://www.ina.iq/1")]
    report = evaluate_pair(first, second, "وزارة العمل العراقية", semantic_status="ready")
    assert report["trusted_jaccard"] == 1.0
    assert report["passed"]


def test_jaccard_partial_overlap():
    assert jaccard(["a", "b"], ["b", "c"]) == 1 / 3
