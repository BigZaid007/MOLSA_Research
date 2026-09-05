from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import Request

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
SUPPORTED = ("en", "ar")
_CACHE: dict[str, dict[str, Any]] = {}


def load_translations(lang: str) -> dict[str, Any]:
    if lang not in SUPPORTED:
        lang = "en"
    if lang not in _CACHE:
        path = TRANSLATIONS_DIR / f"{lang}.json"
        with open(path, encoding="utf-8") as handle:
            _CACHE[lang] = json.load(handle)
    return _CACHE[lang]


def resolve_lang(request: Request) -> str:
    query = request.query_params.get("lang")
    if query in SUPPORTED:
        return query
    cookie = request.cookies.get("lang")
    if cookie in SUPPORTED:
        return cookie
    return "en"


def lookup(data: dict[str, Any], key: str) -> str:
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return key
        current = current[part]
    return current if isinstance(current, str) else key


def make_translator(lang: str) -> Callable[..., str]:
    data = load_translations(lang)

    def t(key: str, **kwargs: Any) -> str:
        text = lookup(data, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                return text
        return text

    return t


def text_direction(lang: str) -> str:
    return "rtl" if lang == "ar" else "ltr"
