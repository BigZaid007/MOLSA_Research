"""Detect low-value / spam social and web hits from public search indexes."""

from __future__ import annotations

import re
from typing import Iterable

from models import ResearchItem

HIDDEN_DESCRIPTION = (
    "the site owner hides",
    "hides the web page description",
    "no description available",
    "this content isn't available",
    "this content isn\'t available",
)

PAGE_CARD = (
    "talking about this",
    "were here",
    "people follow this",
    "likes ·",
    "like this",
)

FAKE_MINISTRY = (
    "آلعمل",
    "وزارة آلعمل",
    "اخبار وزارة آل",
)

FOREIGN_MINISTRY = (
    "وزارة العمل الأردنية",
    "وزارة العمل الاردنية",
    "وزارة العمل المصرية",
    "وزارة العمل السعودية",
    "وزارة العمل الكويتية",
    "وزارة العمل اللبنانية",
    "وزارة العمل السورية",
    "وزارة العمل الفلسطينية",
    "وزارة العمل التونسية",
    "وزارة العمل المغربية",
    "وزارة العمل القطرية",
    "وزارة العمل الإماراتية",
    "وزارة العمل الاماراتية",
    "وزارة العمل البحرينية",
    "وزارة العمل العمانية",
    "وزارة العمل اليمنية",
    "jordanian ministry of labour",
    "jordan ministry of labour",
    "ministry of labour jordan",
    "egyptian ministry of labour",
    "saudi ministry of labour",
)

FOREIGN_COUNTRY = (
    "الأردن",
    "الاردن",
    "الأردنية",
    "الاردنية",
    "jordan",
    "jordanian",
    "مصر",
    "المصرية",
    "egypt",
    "egyptian",
    "السعودية",
    "السعودي",
    "saudi",
    "الكويت",
    "kuwait",
    "الإمارات",
    "الامارات",
    "uae",
    "لبنان",
    "lebanon",
    "سوريا",
    "syria",
    "اليمن",
    "yemen",
    "فلسطين",
    "palestine",
    "قطر",
    "qatar",
    "البحرين",
    "bahrain",
    "عُمان",
    "عمان",
    "oman",
    "تونس",
    "tunisia",
    "المغرب",
    "morocco",
)

IRAQ_SIGNALS = (
    "العراق",
    "العراقية",
    "العراقي",
    "iraq",
    "iraqi",
    "molsa",
    "بغداد",
    "baghdad",
    "molsa.gov.iq",
)

FOREIGN_TLDS = (".jo", ".eg", ".sa", ".kw", ".ae", ".lb", ".sy", ".ye", ".qa", ".bh", ".om", ".tn", ".ma")

LIKES_RE = re.compile(r"\b\d[\d,.\s]{0,12}\s*likes\b", re.I)
MASH_SPLIT_RE = re.compile(r"\s*(?:\.{3}|…|\s+\|\s+)\s*")
HASHTAG_ONLY_RE = re.compile(r"^[#＃][\w\u0600-\u06FF_]+$")


def _blob(title: str, snippet: str) -> str:
    return f"{title or ''} {snippet or ''}".strip()


def _norm(text: str) -> str:
    from services.arabic import normalize_arabic

    return normalize_arabic(text)


def is_mashed_title(title: str) -> bool:
    title = (title or "").strip()
    if len(title) < 50:
        return False
    parts = [p for p in MASH_SPLIT_RE.split(title) if len(p.strip()) > 8]
    if len(parts) >= 3:
        return True
    if title.count("وزارة العمل") >= 2 and len(title) > 70:
        return True
    if title.count("|") >= 2:
        return True
    return False


def tidy_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return title
    if not is_mashed_title(title):
        return title[:160]
    parts = [p.strip(" -·") for p in MASH_SPLIT_RE.split(title) if 10 <= len(p.strip()) <= 90]
    if parts:
        return parts[0]
    return title[:120]


def is_page_card(text: str) -> bool:
    low = _norm(text)
    if any(token in low for token in PAGE_CARD):
        return True
    return bool(LIKES_RE.search(low))


def is_foreign_labour(title: str, snippet: str, url: str = "") -> bool:
    """Drop other countries' labour ministries when this app is Iraq-focused."""
    blob = _norm(_blob(title, snippet))
    low_url = (url or "").lower()
    if any(token in blob for token in FOREIGN_MINISTRY):
        return True
    if any(low_url.endswith(tld) or tld + "/" in low_url for tld in FOREIGN_TLDS):
        if not any(signal in blob or signal in low_url for signal in IRAQ_SIGNALS):
            return True
    foreign = any(token in blob for token in FOREIGN_COUNTRY)
    iraq = any(signal in blob or signal in low_url for signal in IRAQ_SIGNALS)
    if foreign and not iraq and ("وزارة العمل" in blob or "ministry of labour" in blob or "ministry of labor" in blob):
        return True
    return False


def is_hard_spam(title: str, snippet: str, url: str = "", kind: str = "") -> bool:
    title = title or ""
    snippet = snippet or ""
    blob = _norm(_blob(title, snippet))
    if not blob:
        return True
    if any(token in blob for token in HIDDEN_DESCRIPTION):
        return True
    if any(token in blob for token in FAKE_MINISTRY):
        return True
    if is_foreign_labour(title, snippet, url):
        return True
    if HASHTAG_ONLY_RE.match(title.strip()):
        return True
    if kind in {"page", "profile", "tag", "subreddit"} and is_page_card(blob):
        return True
    if is_mashed_title(title) and (is_page_card(blob) or kind in {"page", "profile"}):
        return True
    if len(blob) < 24 and kind in {"page", "profile", "tag"}:
        return True
    low_url = (url or "").lower()
    if "facebook.com" in low_url and kind == "page" and is_mashed_title(title):
        return True
    return False


def is_clean_official_page(title: str, snippet: str) -> bool:
    title = (title or "").strip()
    if is_mashed_title(title) or is_page_card(_blob(title, snippet)):
        return False
    return title in {
        "وزارة العمل والشؤون الاجتماعية",
        "وزارة العمل العراقية",
        "Iraqi Ministry of Labour",
        "Ministry of Labour and Social Affairs",
    } or title.startswith("وزارة العمل والشؤون الاجتماعية")


def fingerprint(title: str, snippet: str) -> str:
    text = _norm(f"{title} {snippet}")
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text)
    return " ".join(text.split()[:16])


def filter_social_hits(hits: list[dict]) -> list[dict]:
    kept: list[dict] = []
    seen_fp: set[str] = set()
    official_page_kept = False

    for item in hits:
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        url = item.get("url") or ""
        kind = (item.get("metadata") or {}).get("post_kind") or ""
        if is_hard_spam(title, snippet, url, kind):
            continue
        if kind in {"page", "profile"}:
            if official_page_kept or not is_clean_official_page(title, snippet):
                continue
            official_page_kept = True
        fp = fingerprint(title, snippet)
        if fp and fp in seen_fp:
            continue
        if fp:
            seen_fp.add(fp)
        if is_mashed_title(title):
            item["title"] = tidy_title(title)
        kept.append(item)
    return kept


def filter_research_items(items: Iterable[ResearchItem]) -> list[ResearchItem]:
    kept: list[ResearchItem] = []
    seen_fp: set[str] = set()
    official_page_kept = False

    for item in items:
        title = item.title or ""
        snippet = item.content or item.description or ""
        kind = (item.metadata or {}).get("post_kind") or ""
        source = (item.source or "").lower()
        social = source in {
            "facebook",
            "instagram",
            "linkedin",
            "x",
            "tiktok",
            "reddit",
            "telegram",
        }
        if is_hard_spam(title, snippet, item.url or "", kind):
            continue
        if social and kind in {"page", "profile"}:
            if official_page_kept or not is_clean_official_page(title, snippet):
                continue
            official_page_kept = True
        fp = fingerprint(title, snippet)
        if fp and fp in seen_fp:
            continue
        if fp:
            seen_fp.add(fp)
        if is_mashed_title(title):
            item.title = tidy_title(title)
        kept.append(item)
    return kept
