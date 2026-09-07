from extractors.article import extract_from_html
from services.agencies import agency_label, match_agency, selected_agencies
from services.export import build_report
from services.focus import build_search_queries
from services.processor import AGENCY_SOURCES, WEB_SOURCES, resolve_sources
from services.urls import canonicalize_url


def test_named_agency_domains_map_to_arabic_labels():
    assert agency_label("https://www.alsumaria.tv/news/123") == "السومرية"
    assert agency_label("https://baghdad24.news/story") == "بغداد 24"
    assert agency_label("https://www.aljazeera.net/news/iraq") == "الجزيرة"
    assert match_agency("https://www.ina.iq/ar/123").id == "ina"
    assert match_agency("https://www.rudaw.net/arabic/x").id == "rudaw"
    assert match_agency("https://www.alghadpress.com/news/1").id == "alghadpress"


def test_selected_agencies_defaults_to_full_catalog():
    assert len(selected_agencies(None)) >= 3
    assert [item.id for item in selected_agencies(["alsumaria", "jazeera"])] == [
        "alsumaria",
        "jazeera",
    ]


def test_agency_hit_lands_in_agencies_export_section():
    report = build_report(
        {
            "results": [
                {
                    "title": "خبر السومرية عن الوزارة",
                    "source": "agencies",
                    "platform": "alsumaria",
                    "agency_label": "السومرية",
                    "url": "https://www.alsumaria.tv/molsa",
                }
            ]
        }
    )
    agencies = next(section for section in report.sections if section.key == "agencies")
    assert agencies.rows[0] == ("1-", "خبر السومرية عن الوزارة", "السومرية")


def test_web_sources_include_news_connector():
    assert "news" in WEB_SOURCES
    assert "rss" in WEB_SOURCES
    assert "agencies" in AGENCY_SOURCES
    assert "google" in WEB_SOURCES


def test_all_tab_defaults_to_web_agencies_and_telegram():
    sources = resolve_sources("all", None)
    assert WEB_SOURCES <= set(sources)
    assert AGENCY_SOURCES <= set(sources)
    assert "telegram" in sources
    assert "facebook" not in sources


def test_all_tab_keeps_selected_sources():
    assert resolve_sources("all", ["google", "facebook", "agencies"]) == [
        "google",
        "facebook",
        "agencies",
    ]


def test_website_tab_still_excludes_social_and_agencies():
    sources = resolve_sources("news", ["google", "facebook", "agencies"])
    assert sources == ["google"]
    assert "facebook" not in sources
    assert "agencies" not in sources


def test_repeated_chips_do_not_duplicate_queries():
    topic = "وزارة العمل العراقية, وزير العمل العراقي, قرارات وزارة العمل العراقية, وزارة العمل العراقية, وزير العمل العراقي"
    queries = build_search_queries(topic)
    assert queries.count("وزارة العمل العراقية") <= 1
    joined = " ".join(queries)
    assert joined.count("وزارة العمل العراقية, وزارة العمل العراقية") == 0


def test_ministry_query_does_not_expand_iraq_suffix():
    queries = build_search_queries("وزارة العمل والشؤون الاجتماعية العراقية")
    assert "العراقية" not in queries
    assert not any(query.startswith("العراقية ") for query in queries)


def test_canonicalize_url_strips_tracking_and_www():
    left = canonicalize_url("https://www.alsumaria.tv/news/1?utm_source=x&fbclid=1")
    right = canonicalize_url("https://alsumaria.tv/news/1/")
    assert left == right or left.rstrip("/") == right.rstrip("/")


def test_jsonld_newsarticle_extraction():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"NewsArticle","headline":"وزارة العمل تعلن قرارا","articleBody":"نص الخبر الكامل هنا عن الوزارة.","datePublished":"2026-09-06","author":{"name":"واع"}}
    </script>
    </head><body></body></html>
    """
    extracted = extract_from_html(html, "https://www.ina.iq/story")
    assert "وزارة العمل تعلن قرارا" in (extracted.get("title") or "")
    assert "نص الخبر الكامل" in (extracted.get("content") or "")
