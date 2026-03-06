from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
import hashlib
from athena.core.schemas import ContentItemCreate

class BaseScraper(ABC):
    def __init__(self, source_id: str):
        self.source_id = source_id

    @abstractmethod
    async def fetch(self) -> List[ContentItemCreate]:
        """Fetch content from the source and return a list of normalized items."""
        pass

    def generate_content_hash(self, text: str) -> str:
        """Generate a SHA-256 hash of the content for deduplication."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
