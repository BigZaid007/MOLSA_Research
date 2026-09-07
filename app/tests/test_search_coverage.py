from datetime import datetime
from types import SimpleNamespace

import pytest

from connectors.agencies import _keep_item, _matches_ministry, _recent_enough
from models import ContentType, ResearchItem
from services.focus import (
    agency_query_terms,
    ddgs_timelimit,
    filter_ministry_results,
    google_news_when_from_timelimit,
    google_news_when_suffix,
    is_homepage_url,
)
from services.processor import (
    AGENCY_SOURCES,
    SOCIAL_SOURCES,
    WEB_SOURCES,
    grouped_sources,
    resolve_sources,
    ResearchProcessor,
)


def test_ddgs_timelimit_maps_windows():
    assert ddgs_timelimit(None, None) is None
    assert ddgs_timelimit("2026-09-06", "2026-09-07") == "d"
    assert ddgs_timelimit("2026-09-01", "2026-09-07") == "w"
    assert ddgs_timelimit("2026-08-08", "2026-09-07") == "m"


def test_google_news_when_suffix_for_24h_window():
    assert google_news_when_suffix("2026-09-06", "2026-09-07") == " when:1d"
    assert google_news_when_from_timelimit("d") == " when:1d"
    assert google_news_when_from_timelimit("w") == " when:7d"


def test_agency_rss_keeps_recent_ministry_entries():
    now = datetime.now()
    assert _recent_enough(now, "d") is True
    assert _recent_enough(datetime(2024, 1, 1), "d") is False
    assert _recent_enough(None, "d") is True
    assert _recent_enough(datetime(2024, 1, 1), None) is True


def test_agency_query_terms_shorten_ministry_topic():
    long_query = "وزارة العمل والشؤون الاجتماعية العراقية"
    short = agency_query_terms(long_query)
    assert short == "وزارة العمل"
    assert '"' not in short


def test_combined_all_sources_default_to_web_agencies_and_telegram():
    sources = resolve_sources("all", None)
    assert WEB_SOURCES <= set(sources)
    assert AGENCY_SOURCES <= set(sources)
    assert "telegram" in sources
    assert "facebook" not in sources
    groups = grouped_sources(sources)
    assert "google" in groups["web"]
    assert "news" in groups["web"]
    assert "rss" in groups["web"]
    assert "agencies" in groups["agencies"]


def test_trusted_domain_without_ministry_phrase_is_dropped():
    item = ResearchItem(
        title="خبر من الوكالة",
        url="https://www.ina.iq/ar/123",
        source="agencies",
        content_type=ContentType.NEWS,
        description="إعلان جديد",
        metadata={"agency_id": "ina", "agency_label": "واع"},
    )
    kept = filter_ministry_results(
        [item], "وزارة العمل والشؤون الاجتماعية العراقية"
    )
    assert kept == []


def test_ministry_named_agency_hit_is_kept(monkeypatch):
    monkeypatch.setattr(
        "services.semantic.similarity_scores", lambda topic, items: [0.0] * len(items)
    )
    item = ResearchItem(
        title="وزارة العمل تعلن عن فرص عمل",
        url="https://www.ina.iq/ar/123",
        source="agencies",
        content_type=ContentType.NEWS,
        description="إعلان جديد",
        metadata={"agency_id": "ina", "agency_label": "واع"},
    )
    kept = filter_ministry_results(
        [item], "وزارة العمل والشؤون الاجتماعية العراقية"
    )
    assert kept
    assert kept[0].url == item.url


def test_homepage_url_is_dropped_even_with_ministry_title():
    item = ResearchItem(
        title="وزارة العمل والشؤون الاجتماعية",
        url="https://www.molsa.gov.iq/",
        source="google",
        content_type=ContentType.WEBSITE,
        description="الموقع الرسمي",
    )
    assert is_homepage_url(item.url)
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept == []


def test_social_snippet_ministry_phrase_is_kept(monkeypatch):
    monkeypatch.setattr(
        "services.semantic.similarity_scores", lambda topic, items: [0.0] * len(items)
    )
    item = ResearchItem(
        title="منشور جديد",
        url="https://www.facebook.com/posts/2",
        source="facebook",
        content_type=ContentType.SOCIAL,
        description="وزير العمل يعلن عن قرارات جديدة",
        metadata={"post_kind": "post"},
    )
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept
    assert kept[0].url == item.url


def test_social_post_with_ministry_phrase_is_kept(monkeypatch):
    monkeypatch.setattr(
        "services.semantic.similarity_scores", lambda topic, items: [0.0] * len(items)
    )
    item = ResearchItem(
        title="وزارة العمل العراقية تعلن",
        url="https://www.facebook.com/posts/1",
        source="facebook",
        content_type=ContentType.SOCIAL,
        description="خبر الوزارة",
        metadata={"post_kind": "post"},
    )
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept
    assert kept[0].url == item.url


def test_other_ministry_title_is_dropped_despite_labour_footer():
    item = ResearchItem(
        title="تظاهر عشرات الخريجين أمام مقر وزارة النفط وسط العاصمة العراقية",
        url="https://www.tiktok.com/@x/video/1",
        source="tiktok",
        content_type=ContentType.SOCIAL,
        description="وزارة العمل والشؤون الاجتماعية. البريد الإلكتروني قسم التصفية",
        content="وزارة العمل والشؤون الاجتماعية للتواصل",
        metadata={"post_kind": "post"},
    )
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept == []


def test_labour_phrase_only_in_contact_footer_is_dropped():
    item = ResearchItem(
        title="ارتفاع أسعار النفط",
        url="https://www.shafaq.com/story/oil",
        source="agencies",
        content_type=ContentType.NEWS,
        description="أسواق الطاقة",
        content="تواصل مع وزارة العمل والشؤون الاجتماعية عبر الموقع",
        metadata={"agency_id": "shafaq"},
    )
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept == []


def test_ministry_named_in_article_body_is_kept(monkeypatch):
    monkeypatch.setattr(
        "services.semantic.similarity_scores", lambda topic, items: [0.0] * len(items)
    )
    item = ResearchItem(
        title="إعلان جديد عن التعيينات",
        url="https://www.ina.iq/story/jobs",
        source="agencies",
        content_type=ContentType.NEWS,
        description="خبر عراقي",
        content="أعلنت وزارة العمل والشؤون الاجتماعية عن فتح باب التقديم للتعيينات في بغداد.",
        metadata={"agency_id": "ina"},
    )
    kept = filter_ministry_results([item], "وزارة العمل العراقية")
    assert kept
    assert kept[0].url == item.url


def test_low_cosine_keeps_trusted_ministry_hits(monkeypatch):
    titled = ResearchItem(
        title="وزارة العمل تعلن",
        url="https://www.ina.iq/titled",
        source="agencies",
        content_type=ContentType.NEWS,
        description="تفاصيل",
        metadata={"agency_id": "ina"},
    )
    body_only = ResearchItem(
        title="خبر عام",
        url="https://www.ina.iq/body",
        source="agencies",
        content_type=ContentType.NEWS,
        description="وزارة العمل والشؤون الاجتماعية",
        metadata={"agency_id": "ina"},
    )
    untrusted = ResearchItem(
        title="خبر عام",
        url="https://random-blog.example/x",
        source="google",
        content_type=ContentType.WEBSITE,
        description="وزارة العمل والشؤون الاجتماعية",
    )

    def fake_scores(topic, items):
        return [0.22 for _ in items]

    monkeypatch.setattr("services.semantic.similarity_scores", fake_scores)
    kept = filter_ministry_results(
        [titled, body_only, untrusted], "وزارة العمل العراقية"
    )
    urls = {item.url for item in kept}
    assert titled.url in urls
    assert body_only.url in urls
    assert untrusted.url not in urls


def test_agency_rss_requires_ministry_phrase_not_bare_labour():
    assert not _matches_ministry("سوق العمل ينتعش", "ارتفاع التشغيل في بغداد", "وزارة العمل")
    assert _matches_ministry("وزارة العمل تعلن", "خبر عاجل", "وزارة العمل")
    assert not _keep_item("فيضان دجلة", "ارتفاع المناسيب", "https://www.ina.iq/1", None)
    assert _keep_item(
        "وزارة العمل تعلن", "خبر", "https://www.ina.iq/story/1", None
    )
    assert not _keep_item("وزارة العمل", "رسمي", "https://www.ina.iq/", None)


@pytest.mark.asyncio
async def test_google_connector_merges_news_hits(monkeypatch):
    from connectors.google import GoogleConnector

    async def fake_text(query, **kwargs):
        assert kwargs.get("timelimit") == "d"
        if "site:" in query:
            return [
                {
                    "title": "الموقع الرسمي",
                    "url": "https://www.molsa.gov.iq/news",
                    "snippet": "وزارة العمل",
                }
            ]
        return [
            {
                "title": "صفحة عامة",
                "url": "https://example.com/labour",
                "snippet": "وزارة العمل",
            }
        ]

    async def fake_rss(self, query, limit=10, timelimit=None):
        assert timelimit == "d"
        return [
            {
                "title": "RSS",
                "url": "https://news.google.com/rss/1",
                "snippet": "وزارة العمل العراقية",
            }
        ]

    monkeypatch.setattr("connectors.google.ddgs_text", fake_text)
    monkeypatch.setattr(GoogleConnector, "_google_news_search", fake_rss)

    results = await GoogleConnector().search("وزارة العمل العراقية", timelimit="d")
    urls = {item["url"] for item in results}
    assert "https://news.google.com/rss/1" in urls
    assert "https://www.molsa.gov.iq/news" in urls
    assert "https://example.com/labour" in urls


@pytest.mark.asyncio
async def test_agencies_connector_dedicated_iraqi_wires_unquoted(monkeypatch):
    from connectors.agencies import AgenciesConnector, PRIORITY_AGENCY_IDS

    captured: list[str] = []

    async def fake_text(query, **kwargs):
        captured.append(query)
        mapping = {
            "ina.iq": "https://www.ina.iq/123",
            "ninanews.com": "https://www.ninanews.com/123",
            "shafaq.com": "https://www.shafaq.com/123",
            "alsumaria.tv": "https://www.alsumaria.tv/123",
            "rudaw.net": "https://www.rudaw.net/123",
            "almadapaper.net": "https://almadapaper.net/123",
            "baghdad24.news": "https://baghdad24.news/123",
        }
        hits = []
        for domain, url in mapping.items():
            if f"site:{domain}" in query:
                hits.append(
                    {
                        "title": f"وزارة العمل على {domain}",
                        "url": url,
                        "snippet": "خبر عاجل",
                    }
                )
        return hits

    async def fake_feed(self, query, agency, timelimit=None):
        if agency.id == "ina":
            return [
                {
                    "title": "وزارة العمل من RSS",
                    "url": "https://www.ina.iq/rss-item",
                    "snippet": "وزارة العمل",
                    "published_date": datetime(2026, 9, 7),
                }
            ]
        return []

    async def fake_gnews(self, query, limit=10, timelimit=None):
        return []

    monkeypatch.setattr("connectors.agencies.ddgs_text", fake_text)
    monkeypatch.setattr(AgenciesConnector, "_feed_fallback", fake_feed)
    monkeypatch.setattr(AgenciesConnector, "_google_news_search", fake_gnews)

    connector = AgenciesConnector()
    connector.selected_ids = list(PRIORITY_AGENCY_IDS)
    results = await connector.search(
        "وزارة العمل والشؤون الاجتماعية العراقية", timelimit="d"
    )

    assert len(captured) <= 6
    for domain in ("ina.iq", "ninanews.com", "shafaq.com", "alsumaria.tv"):
        site_queries = [query for query in captured if query.startswith(f"site:{domain}")]
        assert site_queries, domain
        assert all('"' not in query for query in site_queries)
        assert "وزارة العمل" in site_queries[0]

    batched = [query for query in captured if query.count("site:") > 1]
    assert batched
    assert "site:rudaw.net" in batched[0]
    assert "site:almadapaper.net" in batched[0]
    assert "site:baghdad24.news" in batched[0]

    urls = {item["url"] for item in results}
    assert "https://www.ina.iq/123" in urls
    assert "https://www.ina.iq/rss-item" in urls
    assert "https://www.ninanews.com/123" in urls
    assert "https://www.shafaq.com/123" in urls
    assert "https://www.alsumaria.tv/123" in urls
    assert "https://www.rudaw.net/123" in urls


@pytest.mark.asyncio
async def test_social_search_passes_timelimit(monkeypatch):
    from connectors.facebook import FacebookConnector

    seen = {}

    async def fake_text(query, **kwargs):
        seen["timelimit"] = kwargs.get("timelimit")
        return [
            {
                "title": "منشور وزارة العمل",
                "url": "https://www.facebook.com/posts/1",
                "snippet": "وزارة العمل العراقية",
            }
        ]

    monkeypatch.setattr("connectors.social.ddgs_text", fake_text)
    results = await FacebookConnector().search("وزارة العمل", timelimit="d")
    assert seen.get("timelimit") == "d"
    assert results


@pytest.mark.asyncio
async def test_social_search_keeps_snippet_entity(monkeypatch):
    from connectors.facebook import FacebookConnector

    async def fake_text(query, **kwargs):
        return [
            {
                "title": "منشور جديد",
                "url": "https://www.facebook.com/posts/9",
                "snippet": "وزارة العمل العراقية تعلن عن قرارات",
            }
        ]

    monkeypatch.setattr("connectors.social.ddgs_text", fake_text)
    results = await FacebookConnector().search("وزارة العمل")
    assert results
    assert results[0]["url"].endswith("/posts/9")


@pytest.mark.asyncio
async def test_telegram_skips_ddgs_when_official_posts_exist(monkeypatch):
    from connectors.telegram import TelegramConnector

    called = {"ddgs": False}

    async def fake_scrape(self, channel, query):
        return [
            {
                "title": "وزارة العمل تعلن",
                "url": "https://t.me/molsa2023/12",
                "snippet": "وزارة العمل والشؤون الاجتماعية",
                "source": "telegram",
                "metadata": {"official": True, "post_kind": "post"},
            }
        ]

    async def fake_text(*args, **kwargs):
        called["ddgs"] = True
        return []

    monkeypatch.setattr(TelegramConnector, "_scrape_channel", fake_scrape)
    monkeypatch.setattr("connectors.social.ddgs_text", fake_text)
    results = await TelegramConnector().search("وزارة العمل")
    assert results
    assert results[0]["url"] == "https://t.me/molsa2023/12"
    assert called["ddgs"] is False


@pytest.mark.asyncio
async def test_enrichment_keeps_snippet_when_fetch_fails(monkeypatch):
    processor = ResearchProcessor()
    item = ResearchItem(
        title="وزارة العمل تعلن",
        url="https://www.shafaq.com/story",
        source="agencies",
        content_type=ContentType.NEWS,
        description="snippet only",
        content="snippet only",
        metadata={"agency_id": "shafaq"},
    )

    async def fail_fetch(candidate):
        candidate.metadata["status"] = "partial"
        candidate.metadata["fetch_error"] = "timeout"
        return candidate

    monkeypatch.setattr(processor, "_fetch_and_extract", fail_fetch)
    kept = await processor._enrich_articles([item], max_results=10)
    assert any(entry.url == item.url for entry in kept)
    assert any((entry.metadata or {}).get("status") == "partial" for entry in kept)


@pytest.mark.asyncio
async def test_fetch_and_extract_returns_item_on_http_error(monkeypatch):
    processor = ResearchProcessor()
    item = ResearchItem(
        title="وزارة العمل",
        url="https://www.nina.news.com/x",
        source="agencies",
        content_type=ContentType.NEWS,
        description="keep me",
    )

    class DummyClient:
        async def get(self, url):
            return SimpleNamespace(status_code=403, text="", url=url)

    monkeypatch.setattr(
        "connectors.base.BaseConnector.get_client", classmethod(lambda cls: DummyClient())
    )
    kept = await processor._fetch_and_extract(item)
    assert kept is item
    assert kept.metadata.get("status") == "partial"


def test_rank_blends_semantic_similarity(monkeypatch):
    processor = ResearchProcessor()
    close = ResearchItem(
        title="إعلان رواتب المتقاعدين",
        url="https://www.ina.iq/a",
        source="agencies",
        content_type=ContentType.NEWS,
        description="وزارة العمل والشؤون الاجتماعية",
        content="وزارة العمل والشؤون الاجتماعية تعلن",
        metadata={"agency_id": "ina"},
    )
    far = ResearchItem(
        title="إعلان رواتب المتقاعدين",
        url="https://www.ina.iq/b",
        source="agencies",
        content_type=ContentType.NEWS,
        description="وزارة العمل والشؤون الاجتماعية",
        content="وزارة العمل والشؤون الاجتماعية تعلن",
        metadata={"agency_id": "ina"},
    )

    def fake_scores(topic, items):
        return [0.92 if item is close else 0.12 for item in items]

    monkeypatch.setattr("services.processor.similarity_scores", fake_scores)
    ranked = processor._rank_results(
        [far, close], "وزارة العمل والشؤون الاجتماعية العراقية"
    )
    assert ranked[0] is close


def test_filter_orders_by_semantic_when_keywords_match(monkeypatch):
    items = [
        ResearchItem(
            title="وزارة العمل اجتماع روتيني",
            url=f"https://www.ina.iq/{idx}",
            source="agencies",
            content_type=ContentType.NEWS,
            description="وزارة العمل والشؤون الاجتماعية",
            metadata={"agency_id": "ina"},
        )
        for idx in range(3)
    ]

    def fake_scores(topic, docs):
        return [0.2, 0.95, 0.3]

    monkeypatch.setattr("services.semantic.similarity_scores", fake_scores)
    kept = filter_ministry_results(
        items, "وزارة العمل والشؤون الاجتماعية العراقية"
    )
    assert kept[0].url == "https://www.ina.iq/1"


def test_date_window_drops_undated_off_topic_and_does_not_restore():
    processor = ResearchProcessor()
    junk = ResearchItem(
        title="فيضان دجلة",
        url="https://almadapaper.net/451732",
        source="rss",
        content_type=ContentType.RSS,
        description="ارتفاع المناسيب",
        published_date=None,
    )
    named = ResearchItem(
        title="وزارة العمل تعلن",
        url="https://www.ina.iq/story/1",
        source="agencies",
        content_type=ContentType.NEWS,
        description="خبر الوزارة",
        published_date=None,
        metadata={"agency_id": "ina"},
    )
    kept = processor._filter_by_date(
        [junk, named],
        "2026-09-06",
        "2026-09-07",
        topic="وزارة العمل العراقية",
    )
    urls = {item.url for item in kept}
    assert named.url in urls
    assert junk.url not in urls


def test_query_limit_uses_three_variants():
    from services.processor import QUERY_LIMIT, search_queries_for_run

    assert QUERY_LIMIT == 3
    queries = ["وزارة العمل العراقية", "Iraqi Ministry of Labour", "وزارة العمل البصرة", "extra"]
    assert search_queries_for_run(queries, "وزارة العمل") == queries[:3]


def test_news_is_a_web_source():
    from services.processor import DEFAULT_ALL_SOURCE_LIST, WEB_SOURCE_LIST

    assert "news" in WEB_SOURCE_LIST
    assert "rss" in WEB_SOURCE_LIST
    assert DEFAULT_ALL_SOURCE_LIST[0] == "rss"
    assert "telegram" in DEFAULT_ALL_SOURCE_LIST
    assert "facebook" not in DEFAULT_ALL_SOURCE_LIST


def test_split_source_waves_puts_ddgs_in_gapfill():
    from services.processor import split_source_waves

    waves = split_source_waves(["rss", "news", "google", "bing", "agencies", "telegram", "facebook"])
    assert waves["trusted"][:4] == ["rss", "news", "agencies", "telegram"]
    assert waves["gapfill"] == ["google", "bing"]
    assert waves["exploratory"] == ["facebook"]


def test_arabic_normalization_matches_alef_variants():
    from services.arabic import contains_normalized, normalize_arabic
    from services.focus import has_ministry_entity_phrase

    assert normalize_arabic("وزارة الإعمار") != ""
    assert contains_normalized("وزاره العمل والشؤون الاجتماعية", "وزارة العمل")
    assert has_ministry_entity_phrase("وزاره العمل تعلن")


def test_ddgs_cache_key_includes_backend_and_domains():
    from connectors.ddgs_search import _cache_key

    auto = _cache_key("google", "وزارة العمل", 10, "xa-ar", "d", backend="auto")
    bing = _cache_key("google", "وزارة العمل", 10, "xa-ar", "d", backend="bing")
    assert auto != bing
    with_domains = _cache_key(
        "facebook", "وزارة العمل", 8, "xa-ar", None, backend="auto", domains=("facebook.com",)
    )
    without = _cache_key("facebook", "وزارة العمل", 8, "xa-ar", None, backend="auto")
    assert with_domains != without


def test_telegram_channel_listing_is_noise():
    from connectors.social import is_noise_url

    assert is_noise_url("https://t.me/s/molsa_gov1")
    assert is_noise_url("https://t.me/s/molsa2023?before=18252")
    assert not is_noise_url("https://t.me/molsa2023/18252")
