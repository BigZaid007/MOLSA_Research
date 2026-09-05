"""Focus research on Iraq's Ministry of Labour entity — not general labour/work topics."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from models import ResearchItem

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
]

OFFICIAL_SEARCH_DOMAINS = MINISTRY_DOMAINS[:5] + TRUSTED_NEWS_DOMAINS[:2]

# Always-try official pages when discovery is thin
MINISTRY_SEED_PAGES = [
    {
        "title": "وزارة العمل والشؤون الاجتماعية",
        "url": "https://www.molsa.gov.iq/",
        "snippet": "الموقع الرسمي لوزارة العمل والشؤون الاجتماعية في العراق",
        "source": "google",
    },
    {
        "title": "الأمانة العامة لمجلس الوزراء",
        "url": "https://www.cabinet.iq/",
        "snippet": "قرارات وتصريحات مجلس الوزراء العراقي",
        "source": "google",
    },
    {
        "title": "المكتب الإعلامي لرئيس الوزراء",
        "url": "https://pmo.iq/",
        "snippet": "الموقع الرسمي لمكتب رئيس الوزراء العراقي",
        "source": "google",
    },
    {
        "title": "وكالة الأنباء العراقية",
        "url": "https://www.ina.iq/",
        "snippet": "وكالة الأنباء العراقية — أخبار رسمية",
        "source": "news",
    },
    {
        "title": "وكالة نينا للأنباء",
        "url": "https://www.ninanews.com/",
        "snippet": "وكالة الأنباء العراقية المستقلة",
        "source": "news",
    },
]

ARTICLE_HUBS = [
    "https://www.ina.iq/",
    "https://www.ninanews.com/",
    "https://shafaq.com/ar",
]

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
    text = (topic or "").strip().lower()
    text = text.replace("labor", "labour")
    return " ".join(text.split())


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

    parts = [part.strip() for part in topic.split(",") if part.strip()]
    joined = " ".join(parts) if parts else topic
    add(joined)
    if len(parts) > 1:
        for part in parts[:3]:
            add(part)

    if is_ministry_topic(joined):
        remainder = _strip_known_phrases(joined)
        if remainder:
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


def _google_news_when_suffix(date_from: str | None, date_to: str | None) -> str:
    """Google News supports when:1d / when:7d / when:30d / when:1y."""
    if not date_from and not date_to:
        return ""
    try:
        end = datetime.fromisoformat(date_to) if date_to else datetime.now()
        start = datetime.fromisoformat(date_from) if date_from else end
        days = max(1, (end.date() - start.date()).days + 1)
    except ValueError:
        return ""

    if days <= 1:
        return " when:1d"
    if days <= 7:
        return " when:7d"
    if days <= 30:
        return " when:30d"
    if days <= 365:
        return " when:1y"
    return ""


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

    text = _haystack(item)
    score = 0

    for signal in MINISTRY_POSITIVE:
        if signal.lower() in text:
            score += 3 + min(len(signal) // 10, 5)

    domain = _domain(item.url or "")
    for d in MINISTRY_DOMAINS:
        if domain == d or domain.endswith("." + d):
            score += 8
    for d in TRUSTED_NEWS_DOMAINS:
        if domain == d or domain.endswith("." + d):
            score += 5

    title = (item.title or "").lower()
    if "وزارة العمل" in title or "ministry of labour" in title or "ministry of labor" in title:
        score += 10
    if "وزير العمل" in title or "minister of labour" in title or "minister of labor" in title:
        score += 8

    if score < 6:
        for noise in GENERIC_LABOUR_NOISE:
            if noise.lower() in text:
                score -= 4

    return score


def filter_ministry_results(results: list[ResearchItem], topic: str) -> list[ResearchItem]:
    """Keep / rank results about the ministry when the topic is ministry-focused."""
    if not is_ministry_topic(topic):
        return results

    social_sources = {"facebook", "instagram", "linkedin", "x", "tiktok", "reddit", "telegram"}
    scored: list[tuple[int, ResearchItem]] = []
    for item in results:
        score = ministry_relevance_score(item)
        # Keep social posts/threads more generously — RFD wants public social content
        if (item.source or "").lower() in social_sources and score >= 0:
            score = max(score, 4)
        scored.append((score, item))

    strong = [item for score, item in scored if score >= 6]
    social_keep = [
        item
        for score, item in scored
        if score >= 3 and (item.source or "").lower() in social_sources
    ]
    merged = {id(i): i for i in strong + social_keep}
    if len(merged) >= 3:
        return sorted(
            merged.values(),
            key=lambda i: ministry_relevance_score(i),
            reverse=True,
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for score, item in scored if score > 0]
