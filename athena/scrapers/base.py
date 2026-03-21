from abc import ABC, abstractmethod
from typing import List, Any
import hashlib
from athena.core.schemas import ContentItemCreate


class BaseScraper(ABC):
    def __init__(self, source_id: str):
        self.source_id = source_id

    @abstractmethod
    async def fetch(self, *args, **kwargs) -> List[Any]:
        """Retrieve raw items from the source (raw JSON, XML, HTML)."""

    @abstractmethod
    def parse(self, raw: Any) -> ContentItemCreate:
        """Normalise a single raw item to a ContentItemCreate schema object."""

    async def run(self, *args, **kwargs) -> List[ContentItemCreate]:
        """Orchestrator: fetch raw items, then parse each into ContentItemCreate."""
        raws = await self.fetch(*args, **kwargs)
        results = []
        for raw in raws:
            try:
                results.append(self.parse(raw))
            except Exception as e:
                from loguru import logger
                logger.warning(f"[{self.__class__.__name__}] parse() failed for item: {e}")
                continue
        return results

    def generate_content_hash(self, text: str) -> str:
        """Generate a SHA-256 hash of the content for deduplication."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
