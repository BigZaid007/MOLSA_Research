import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DataParserBase(ABC):
    @abstractmethod
    async def parse(self, item) -> Dict[str, Any]:
        pass


class DataParser(DataParserBase):
    def __init__(self):
        self.parsers = []
    
    async def parse(self, item):
        result = {}
        for parser in self.parsers:
            parsed = await parser.parse(item)
            result.update(parsed)
        return result
