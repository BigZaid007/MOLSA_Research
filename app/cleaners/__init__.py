import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ContentCleanerBase(ABC):
    @abstractmethod
    async def clean_html(self, html_content: str) -> str:
        pass


class ContentCleaner(ContentCleanerBase):
    def __init__(self):
        self.cleaners = []
    
    async def clean_html(self, html_content: str) -> str:
        for cleaner in self.cleaners:
            cleaned = await cleaner.clean_html(html_content)
            if cleaned and cleaned.strip():
                return cleaned
        return html_content
