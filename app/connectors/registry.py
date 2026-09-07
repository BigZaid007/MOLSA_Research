"""Explicit connector registry used by the research processor."""

from __future__ import annotations

from typing import Callable

from .bing import BingConnector
from .facebook import FacebookConnector
from .google import GoogleConnector
from .instagram import InstagramConnector
from .linkedin import LinkedInConnector
from .agencies import AgenciesConnector
from .news import NewsConnector
from .reddit import RedditConnector
from .rss import RSSConnector
from .telegram import TelegramConnector
from .tiktok import TikTokConnector
from .x import XConnector

CONNECTOR_FACTORIES: dict[str, Callable[[], object]] = {
    "google": GoogleConnector,
    "bing": BingConnector,
    "rss": RSSConnector,
    "news": NewsConnector,
    "agencies": AgenciesConnector,
    "reddit": RedditConnector,
    "facebook": FacebookConnector,
    "instagram": InstagramConnector,
    "linkedin": LinkedInConnector,
    "x": XConnector,
    "tiktok": TikTokConnector,
    "telegram": TelegramConnector,
}


def get_connector(source: str):
    factory = CONNECTOR_FACTORIES.get(source)
    if not factory:
        return None
    return factory()
