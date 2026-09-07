"""URL canonicalization for search dedup (courlan / news-please style)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        from courlan import normalize_url

        cleaned = normalize_url(raw, strict=False, strip_tracking=True)
        if cleaned:
            return cleaned.rstrip("/")
    except Exception:
        pass
    parsed = urlparse(raw)
    host = parsed.netloc.lower().removeprefix("www.")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in TRACKING
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme or "https", host, path, "", urlencode(query), ""))
