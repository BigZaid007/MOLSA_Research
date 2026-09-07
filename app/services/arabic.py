"""Arabic text normalization for MOLSA matching (Alef/Yaa/Taa marbuta/diacritics)."""

from __future__ import annotations

import re
import unicodedata

_TATWEEL = "\u0640"
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_ALIF_RE = re.compile(r"[إأآٱا]")
_YAA_RE = re.compile(r"[ىئ]")
_TAA_RE = re.compile(r"[ةه]")


def _fallback_normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace(_TATWEEL, "")
    text = _DIACRITICS_RE.sub("", text)
    text = _ALIF_RE.sub("ا", text)
    text = _YAA_RE.sub("ي", text)
    text = _TAA_RE.sub("ه", text)
    return text


def normalize_arabic(text: str) -> str:
    """Lowercase, collapse space, and fold Arabic spelling variants."""
    raw = text or ""
    try:
        from pyarabic.araby import (
            normalize_alef,
            normalize_hamza,
            normalize_teh,
            strip_tashkeel,
            strip_tatweel,
        )

        folded = strip_tatweel(strip_tashkeel(raw))
        folded = normalize_hamza(folded)
        folded = normalize_alef(folded)
        folded = normalize_teh(folded)
    except Exception:
        folded = _fallback_normalize(raw)
    folded = folded.replace("labor", "labour")
    return " ".join(folded.lower().split())


def contains_normalized(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return normalize_arabic(needle) in normalize_arabic(haystack)


def any_normalized_phrase(text: str, phrases: tuple[str, ...] | list[str]) -> bool:
    blob = normalize_arabic(text)
    return any(normalize_arabic(phrase) in blob for phrase in phrases if phrase)
