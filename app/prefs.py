from __future__ import annotations

import json
from pathlib import Path

from config.settings import get_settings

PROJECT_DIR = Path(__file__).resolve().parent.parent
PREFS_PATH = PROJECT_DIR / "data" / "app_settings.json"

ALL_SOURCES = (
    "google",
    "bing",
    "rss",
    "news",
    "agencies",
    "reddit",
    "facebook",
    "instagram",
    "linkedin",
    "x",
    "tiktok",
    "telegram",
)


def default_prefs() -> dict:
    env = get_settings()
    enabled = {
        source.strip()
        for source in (env.get("SEARCH_SOURCES", ",".join(ALL_SOURCES)) or "").split(",")
        if source.strip()
    }
    return {
        "max_pages": env.get_int("MAX_PAGES", 10),
        "request_timeout": env.get_int("REQUEST_TIMEOUT", 30),
        "max_concurrent_requests": env.get_int("MAX_CONCURRENT_REQUESTS", 20),
        "auto_save": "true",
        "sources": {source: source in enabled for source in ALL_SOURCES},
        "timeout": env.get_int("REQUEST_TIMEOUT", 30),
        "max_retries": 3,
        "rate_limiting": {"enabled": "true"},
        "language": env.get("LANGUAGE", "en") or "en",
        "theme": env.get("THEME", "light") or "light",
    }


def load_prefs() -> dict:
    prefs = default_prefs()
    if PREFS_PATH.exists():
        try:
            saved = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                prefs.update({key: saved[key] for key in saved if key != "sources"})
                if isinstance(saved.get("sources"), dict):
                    prefs["sources"].update(saved["sources"])
                if isinstance(saved.get("rate_limiting"), dict):
                    prefs["rate_limiting"].update(saved["rate_limiting"])
        except (OSError, json.JSONDecodeError):
            pass
    return prefs


def save_prefs(payload: dict) -> dict:
    current = load_prefs()
    if not isinstance(payload, dict):
        return current
    for key in (
        "max_pages",
        "request_timeout",
        "max_concurrent_requests",
        "auto_save",
        "timeout",
        "max_retries",
        "language",
        "theme",
    ):
        if key in payload:
            current[key] = payload[key]
    if isinstance(payload.get("sources"), dict):
        current["sources"].update(payload["sources"])
    if isinstance(payload.get("rate_limiting"), dict):
        current["rate_limiting"].update(payload["rate_limiting"])
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current
