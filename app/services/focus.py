"""Focus research on Iraq's Ministry of Labour entity — not general labour/work topics."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from models import ResearchItem
from services.arabic import any_normalized_phrase, normalize_arabic

# Phrases that name the ministry/minister entity. Bare «العمل» is not enough.
MINISTRY_ENTITY_PHRASES = (
    "وزارة العمل",
    "وزير العمل",
    "molsa",
    "ministry of labour",
    "ministry of labor",
    "minister of labour",
    "minister of labor",
)
SEMANTIC_KEEP_MIN = 0.40
MINISTRY_RESULT_CAP = 25
SOCIAL_SOURCE_NAMES = {
    "facebook",
    "instagram",
    "linkedin",
    "x",
    "tiktok",
    "reddit",
    "telegram",
}
# Titles about a different Iraqi ministry are not Labour stories, even if a
# footer or contact block mentions MOLSA.
OTHER_IRAQI_MINISTRIES = (
    "وزارة النفط",
    "وزارة التربية",
    "وزارة التعليم العالي",
    "وزارة الصحة",
    "وزارة الداخلية",
    "وزارة الدفاع",
    "وزارة الخارجية",
    "وزارة المالية",
    "وزارة العدل",
    "وزارة الكهرباء",
    "وزارة الإعمار",
    "وزارة الاعمار",
    "وزارة التخطيط",
    "وزارة الزراعة",
    "وزارة التجارة",
    "وزارة الاتصالات",
    "وزارة الثقافة",
    "وزارة الشباب",
    "وزارة النقل",
    "وزارة الموارد المائية",
    "وزارة الهجرة",
    "وزارة الصناعة",
    "ministry of oil",
    "ministry of education",
    "ministry of health",
    "ministry of interior",
    "ministry of defence",
    "ministry of defense",
    "ministry of finance",
)
HOMEPAGE_PATHS = {
    "",
    "/",
    "/ar",
    "/arabic",
    "/en",
    "/iq",
    "/home",
    "/index",
    "/index.html",
    "/index.php",
    "/mihan",
}

# Strong signals that content is about the ministry / minister / official body
MINISTRY_POSITIVE = [
    "وزارة العمل والشؤون الاجتماعية",
    "وزارة العمل العراقية",
    "وزارة العمل العراق",
    "وزارة العمل",
    "وزير العمل",
    "ministry of labour and social affairs",
    "ministry of labor and social affairs",
    "iraqi ministry of labour",
    "iraqi ministry of labor",
    "ministry of labour iraq",
    "ministry of labor iraq",
    "ministry of labour",
    "ministry of labor",
    "minister of labour",
    "minister of labor",
    "molsa",
    "krg ministry of labour",
]

# Official / ministry-related domains (boost + keep short pages)
MINISTRY_DOMAINS = [
    "molsa.gov.iq",
    "mol.gov.iq",
    "lvtd.gov.iq",
    "cabinet.iq",
    "pmo.iq",
    "gov.iq",
]

# High-trust Iraqi news wires used for discovery and ranking
TRUSTED_NEWS_DOMAINS = [
    "ina.iq",
    "ninanews.com",
    "shafaq.com",
    "alsumaria.tv",
    "rudaw.net",
    "iraqinews.com",
    "almadapaper.net",
    "baghdad24.news",
    "mawazin.net",
    "nasnews.com",
    "almirbad.com",
    "alsharqiya.com",
    "imn.iq",
    "alforatnews.iq",
    "kurdistan24.net",
    "alghadpress.com",
    "utv.iq",
]

OFFICIAL_SEARCH_DOMAINS = MINISTRY_DOMAINS[:5] + TRUSTED_NEWS_DOMAINS[:2]

# Listing pages crawled for article links — homepages themselves are never kept.
MINISTRY_LISTING_PAGES = [
    "https://www.molsa.gov.iq/",
    "https://www.ina.iq/",
    "https://www.ninanews.com/",
    "https://shafaq.com/ar",
    "https://www.alsumaria.tv/",
    "https://almadapaper.net/",
    "https://www.rudaw.net/arabic",
    "https://baghdad24.news/",
    "https://www.mawazin.net/",
]
MINISTRY_SEED_PAGES = MINISTRY_LISTING_PAGES

ARTICLE_HUBS = list(MINISTRY_LISTING_PAGES)

CONTACT_FOOTER_MARKERS = (
    "تواصل مع",
    "للتواصل",
    "للاتصال",
    "البريد الإلكتروني",
    "عبر الموقع",
    "contact us",
    "email:",
    "info@",
)

# Platforms that block anonymous HTML — keep snippets only
SKIP_HTML_HOSTS = [
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "reddit.com",
    "t.me",
    "telegram.me",
    "telegram.org",
    "accounts.google.com",
    "login.microsoftonline.com",
]

# Generic labour-market noise — drop unless a ministry signal is also present
GENERIC_LABOUR_NOISE = [
    "سوق العمل",
    "سوق العمل العراقي",
    "بطالة",
    "youth unemployment",
    "labor market",
    "labour market",
    "job search support",
    "decent work",
    "employment opportunities",
    "workers in iraq",
    "عمالة أجنبية",
    "عمالة الاطفال",
    "عمالة الأطفال",
]

# Family of words that should resolve to the Iraqi ministry, not generic jobs
LABOUR_FAMILY = [
    "وزارة العمل",
    "وزير العمل",
    "العمل والشؤون",
    "الشؤون الاجتماعية",
    "شؤون اجتماعية",
    "مولسا",
    "molsa",
    "ministry of labour",
    "ministry of labor",
    "minister of labour",
    "minister of labor",
    "social affairs",
    "labour",
    "labor",
    "العمل",
]

GENERIC_MARKET_PHRASES = [
    "سوق العمل العراقي",
    "سوق العمل",
    "labor market",
    "labour market",
    "job market",
    "العمل في العراق",
    "jobs in iraq",
    "work in iraq",
]

CANONICAL_QUERIES = [
    "وزارة العمل العراقية",
    "وزارة العمل والشؤون الاجتماعية",
    "وزير العمل العراقي",
    "Iraqi Ministry of Labour",
    "Ministry of Labour and Social Affairs Iraq",
]

_KNOWN_PHRASES = sorted(
    {
        *[signal.lower() for signal in MINISTRY_POSITIVE],
        *[token.lower() for token in LABOUR_FAMILY],
        *GENERIC_MARKET_PHRASES,
        "العراقية",
        "العراقي",
        "العراق",
        "iraq",
        "iraqi",
    },
    key=len,
    reverse=True,
)


def _normalize_topic(topic: str) -> str:
    return normalize_arabic(topic)


def _strip_known_phrases(topic: str) -> str:
    remainder = _normalize_topic(topic)
    for phrase in _KNOWN_PHRASES:
        remainder = remainder.replace(phrase, " ")
    return " ".join(remainder.split())


IRAQ_PROVINCES: dict[str, list[str]] = {
    "baghdad": ["بغداد", "Baghdad"],
    "basra": ["البصرة", "Basra", "Basrah"],
    "nineveh": ["نينوى", "الموصل", "Nineveh", "Mosul"],
    "erbil": ["أربيل", "اربيل", "Erbil", "Hawler"],
    "sulaymaniyah": ["السليمانية", "Sulaymaniyah", "Sulaimani"],
    "duhok": ["دهوك", "Duhok", "Dohuk"],
    "kirkuk": ["كركوك", "Kirkuk"],
    "anbar": ["الأنبار", "الانبار", "Anbar"],
    "najaf": ["النجف", "Najaf"],
    "karbala": ["كربلاء", "Karbala"],
    "babil": ["بابل", "الحلة", "Babil", "Babylon", "Hilla"],
    "wasit": ["واسط", "الكوت", "Wasit", "Kut"],
    "diyala": ["ديالى", "بعقوبة", "Diyala", "Baqubah"],
    "maysan": ["ميسان", "العمارة", "Maysan", "Amarah"],
    "muthanna": ["المثنى", "السماوة", "Muthanna", "Samawah"],
    "dhiqar": ["ذي قار", "الناصرية", "Dhi Qar", "Nasiriyah"],
    "qadisiyyah": ["القادسية", "الديوانية", "Qadisiyyah", "Diwaniyah"],
    "saladin": ["صلاح الدين", "تكريت", "Saladin", "Salah al-Din", "Tikrit"],
    "halabja": ["حلبجة", "Halabja"],
}


def province_terms(province: str | None) -> list[str]:
    key = (province or "").strip().lower()
    return list(IRAQ_PROVINCES.get(key) or [])


def is_ministry_topic(topic: str) -> bool:
    """True when the query is about the ministry or the labour-family around it."""
    raw = topic or ""
    if "," in raw:
        return any(is_ministry_topic(part) for part in raw.split(",") if part.strip())
    text = _normalize_topic(raw)
    if not text:
        return False
    if any(phrase in text for phrase in GENERIC_MARKET_PHRASES):
        return True
    if any(signal.lower() in text for signal in MINISTRY_POSITIVE):
        return True
    cleaned = text
    for phrase in GENERIC_MARKET_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = " ".join(cleaned.split())
    return any(token in cleaned for token in LABOUR_FAMILY)


def build_search_queries(
    topic: str,
    date_from: str | None = None,
    date_to: str | None = None,
    province: str | None = None,
) -> list[str]:
    """
    Expand labour-family keywords into short ministry queries.
    Extra words (قرارات، رواتب، pensions) stay attached to the official name.
    Optional province appends governorate aliases.
    """
    topic = (topic or "").strip()
    if not topic:
        return []

    queries: list[str] = []

    def add(q: str):
        q = q.strip(" ,")
        if q and q not in queries:
            queries.append(q)

    parts: list[str] = []
    seen_parts: set[str] = set()
    for part in topic.split(","):
        cleaned = " ".join(part.split())
        if cleaned and cleaned not in seen_parts:
            seen_parts.add(cleaned)
            parts.append(cleaned)
    joined = " ".join(parts) if parts else topic
    add(joined)
    if len(parts) > 1:
        for part in parts[:3]:
            add(part)

    if is_ministry_topic(joined):
        remainder = _strip_known_phrases(joined)
        weak = remainder.lower() in {"العراقية", "العراقي", "العراق", "iraq", "iraqi"}
        if remainder and not weak:
            add(f"{remainder} وزارة العمل العراقية")
            add(f"{remainder} Iraqi Ministry of Labour")
            add(f"{remainder} وزارة العمل والشؤون الاجتماعية")
        else:
            for canonical in CANONICAL_QUERIES:
                add(canonical)

    location = province_terms(province)
    if location:
        located: list[str] = []
        for query in list(queries)[:3]:
            located.append(f"{query} {location[0]}")
            if len(location) > 1:
                located.append(f"{query} {location[1]}")
        for extra in located:
            add(extra)

    return queries[:6]


def date_window_days(date_from: str | None, date_to: str | None) -> int | None:
    """Inclusive calendar-day span, or None when no range is set."""
    if not date_from and not date_to:
        return None
    try:
        end = datetime.fromisoformat(date_to) if date_to else datetime.now()
        start = datetime.fromisoformat(date_from) if date_from else end
        return max(1, (end.date() - start.date()).days + 1)
    except ValueError:
        return None


def ddgs_timelimit(date_from: str | None, date_to: str | None) -> str | None:
    """Map a UI date window onto ddgs timelimit: d / w / m / y."""
    days = date_window_days(date_from, date_to)
    if days is None:
        return None
    # Yesterday + today is the 24h preset's calendar window.
    if days <= 2:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    if days <= 365:
        return "y"
    return None


def google_news_when_suffix(date_from: str | None, date_to: str | None) -> str:
    """Google News supports when:1d / when:7d / when:30d / when:1y."""
    days = date_window_days(date_from, date_to)
    if days is None:
        return ""
    if days <= 2:
        return " when:1d"
    if days <= 7:
        return " when:7d"
    if days <= 30:
        return " when:30d"
    if days <= 365:
        return " when:1y"
    return ""


def google_news_when_from_timelimit(timelimit: str | None) -> str:
    return {
        "d": " when:1d",
        "w": " when:7d",
        "m": " when:30d",
        "y": " when:1y",
    }.get((timelimit or "").lower(), "")


def _google_news_when_suffix(date_from: str | None, date_to: str | None) -> str:
    return google_news_when_suffix(date_from, date_to)


def agency_query_terms(query: str) -> str:
    """Shorter unquoted terms Iraqi wires actually use in headlines."""
    text = (query or "").strip()
    if not text:
        return text
    if is_ministry_topic(text):
        for short in ("وزارة العمل", "وزير العمل"):
            if short in text:
                return short
        return "وزارة العمل"
    return text


def _headline_text(item: ResearchItem) -> str:
    """Title plus short snippet only — ignore fetched body/footers."""
    snippet = (item.description or "")[:220]
    return f"{item.title or ''} {snippet}"


def has_ministry_entity_phrase(text: str) -> bool:
    return any_normalized_phrase(text, MINISTRY_ENTITY_PHRASES)


def title_names_other_ministry(title: str) -> bool:
    blob = title or ""
    if has_ministry_entity_phrase(blob):
        return False
    return any_normalized_phrase(blob, OTHER_IRAQI_MINISTRIES)


def _looks_like_contact_footer(text: str) -> bool:
    blob = normalize_arabic(text)
    if not has_ministry_entity_phrase(blob):
        return False
    return any(normalize_arabic(marker) in blob for marker in CONTACT_FOOTER_MARKERS)


def has_ministry_entity(item: ResearchItem) -> bool:
    if title_names_other_ministry(item.title or ""):
        return False
    source = (item.source or "").lower()
    if source in SOCIAL_SOURCE_NAMES:
        return has_ministry_entity_phrase(item.title or "") or has_ministry_entity_phrase(
            item.description or ""
        )
    if has_ministry_entity_phrase(_headline_text(item)):
        return True
    body = (item.content or "")[:800]
    if body and has_ministry_entity_phrase(body) and not _looks_like_contact_footer(body):
        return True
    return False


def is_trusted_item(item: ResearchItem) -> bool:
    source = (item.source or "").lower()
    meta = item.metadata or {}
    if source in {"agencies", "news", "rss"} or meta.get("agency_id"):
        return True
    if source == "telegram" and (meta.get("official") or "molsa2023" in (item.url or "").lower()):
        return True
    return is_official_domain(item.url or "") or is_trusted_news_domain(item.url or "")


def item_provenance(item: ResearchItem) -> str:
    source = (item.source or "").lower()
    meta = item.metadata or {}
    if source in SOCIAL_SOURCE_NAMES and source != "telegram":
        return "snippet"
    if source == "telegram" and not (meta.get("official") or "molsa2023" in (item.url or "").lower()):
        return "snippet"
    if is_trusted_item(item) or meta.get("status") == "ok":
        return "verified"
    return "indexed"


def is_homepage_url(url: str) -> bool:
    parsed = urlparse(url or "")
    path = (parsed.path or "/").rstrip("/").lower() or "/"
    if path == "/" or path in HOMEPAGE_PATHS:
        return True
    if path.startswith("/mihan"):
        return True
    return False


def _haystack(item: ResearchItem) -> str:
    parts = [
        item.title or "",
        item.description or "",
        item.content or "",
        item.url or "",
        item.source or "",
    ]
    return " ".join(parts).lower()


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def is_official_domain(url: str) -> bool:
    host = _domain(url)
    low = (url or "").lower()
    if "molsa2023" in low and ("t.me" in host or "telegram" in host):
        return True
    return any(host == d or host.endswith("." + d) for d in MINISTRY_DOMAINS)


def is_trusted_news_domain(url: str) -> bool:
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in TRUSTED_NEWS_DOMAINS)


def should_skip_html_fetch(url: str) -> bool:
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in SKIP_HTML_HOSTS)


def ministry_relevance_score(item: ResearchItem) -> int:
    from services.quality import is_foreign_labour

    if is_foreign_labour(item.title or "", item.content or item.description or "", item.url or ""):
        return -20

    text = normalize_arabic(_haystack(item))
    score = 0

    for signal in MINISTRY_POSITIVE:
        if normalize_arabic(signal) in text:
            score += 3 + min(len(signal) // 10, 5)

    named = has_ministry_entity(item)
    domain = _domain(item.url or "")
    if named:
        for d in MINISTRY_DOMAINS:
            if domain == d or domain.endswith("." + d):
                score += 8
        for d in TRUSTED_NEWS_DOMAINS:
            if domain == d or domain.endswith("." + d):
                score += 5

    title = normalize_arabic(item.title or "")
    if any_normalized_phrase(title, ("وزارة العمل", "ministry of labour", "ministry of labor")):
        score += 10
    if any_normalized_phrase(title, ("وزير العمل", "minister of labour", "minister of labor")):
        score += 8

    if score < 6:
        for noise in GENERIC_LABOUR_NOISE:
            if normalize_arabic(noise) in text:
                score -= 4

    return score


def _is_agency_or_trusted(item: ResearchItem) -> bool:
    source = (item.source or "").lower()
    meta = item.metadata or {}
    if source in {"agencies", "news", "rss"} or meta.get("agency_id"):
        return True
    return is_trusted_news_domain(item.url or "")


def _blended_sort_key(item: ResearchItem, semantic: float) -> float:
    return ministry_relevance_score(item) + 10.0 * semantic


def filter_ministry_results(
    results: list[ResearchItem],
    topic: str,
    semantic: list[float] | None = None,
) -> list[ResearchItem]:
    """Keep items that actually name the Iraqi ministry/minister entity."""
    if not is_ministry_topic(topic):
        return results

    candidates: list[ResearchItem] = []
    for item in results:
        if is_homepage_url(item.url or ""):
            continue
        if not has_ministry_entity(item):
            continue
        if ministry_relevance_score(item) <= 0:
            continue
        candidates.append(item)

    if not candidates:
        return []

    from services.semantic import similarity_scores

    if semantic is not None and len(semantic) == len(results):
        by_original = {id(item): score for item, score in zip(results, semantic)}
        sims = [by_original.get(id(item), 0.0) for item in candidates]
    else:
        sims = similarity_scores(topic, candidates)
    model_live = any(score > 0 for score in sims)
    sim_by_id = {id(item): cosine for item, cosine in zip(candidates, sims)}
    kept: list[ResearchItem] = []
    for item in candidates:
        cosine = sim_by_id.get(id(item), 0.0)
        item.metadata["semantic_score"] = cosine
        title_hit = has_ministry_entity_phrase(item.title or "")
        trusted = is_trusted_item(item)
        if trusted:
            kept.append(item)
            continue
        if model_live and cosine < SEMANTIC_KEEP_MIN and not title_hit:
            continue
        kept.append(item)

    kept.sort(
        key=lambda item: _blended_sort_key(item, sim_by_id.get(id(item), 0.0)),
        reverse=True,
    )
    return kept[:MINISTRY_RESULT_CAP]
