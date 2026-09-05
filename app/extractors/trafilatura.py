import asyncio
import logging
from typing import Dict, Any

import httpx

from extractors.article import extract_from_html

logger = logging.getLogger(__name__)


async def _download_html(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


class TrafilaturaExtractor:
    async def extract(self, url: str) -> Dict[str, Any]:
        try:
            html = await _download_html(url)
            return await asyncio.to_thread(extract_from_html, html, url)
        except Exception as e:
            logger.error("Trafilatura extraction failed for %s: %s", url, e)
            return {}


class ReadabilityExtractor:
    async def extract(self, url: str) -> Dict[str, Any]:
        try:
            html = await _download_html(url)
            return await asyncio.to_thread(extract_from_html, html, url)
        except Exception as e:
            logger.error("Readability extraction failed for %s: %s", url, e)
            return {}


class NewspaperExtractor:
    async def extract(self, url: str) -> Dict[str, Any]:
        try:
            html = await _download_html(url)
            return await asyncio.to_thread(extract_from_html, html, url)
        except Exception as e:
            logger.error("Newspaper extraction failed for %s: %s", url, e)
            return {}


class ContentExtractor:
    def __init__(self):
        self.extractors = [
            TrafilaturaExtractor(),
            ReadabilityExtractor(),
            NewspaperExtractor(),
        ]

    async def extract(self, url: str) -> Dict[str, Any]:
        for extractor in self.extractors:
            result = await extractor.extract(url)
            if result and result.get("content"):
                return result
        return {}


class ContentCleaner:
    async def clean_html(self, html_content: str) -> str:
        return html_content


class DataParser:
    async def parse(self, item) -> Dict[str, Any]:
        return {}