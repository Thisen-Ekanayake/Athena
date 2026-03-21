import httpx
import xml.etree.ElementTree as ET
from typing import List, Any
from datetime import datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger

# All 4 required arXiv categories from the acquisition plan
ARXIV_DEFAULT_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR stat.ML"
ARXIV_DEFAULT_MAX_RESULTS = 50


class ArXivScraper(BaseScraper):
    BASE_URL = "https://export.arxiv.org/api/query"
    NAMESPACE = {'atom': 'http://www.w3.org/2005/Atom'}

    async def fetch(self, search_query: str = ARXIV_DEFAULT_QUERY,
                    max_results: int = ARXIV_DEFAULT_MAX_RESULTS) -> List[Any]:
        """Fetch raw arXiv Atom XML entries and return as parsed XML element list."""
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.BASE_URL, params=params, timeout=30.0)
                response.raise_for_status()
                root = ET.fromstring(response.text)
                return root.findall('atom:entry', self.NAMESPACE)
            except Exception as e:
                logger.error(f"Error fetching from ArXiv: {e}")
                raise e

    def parse(self, entry: Any) -> ContentItemCreate:
        """Normalise a single arXiv Atom XML entry to ContentItemCreate."""
        ns = self.NAMESPACE

        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        abstract_url = entry.find('atom:id', ns).text.strip()
        published_str = entry.find('atom:published', ns).text.strip()
        published_at = datetime.fromisoformat(published_str.replace('Z', '+00:00'))

        authors = [
            author.find('atom:name', ns).text
            for author in entry.findall('atom:author', ns)
            if author.find('atom:name', ns) is not None
        ]
        abstract = (entry.find('atom:summary', ns).text or "").strip()

        # Extract the arxiv_id and PDF URL
        arxiv_id = abstract_url.split('/')[-1]
        # Atom feed uses abs/ URLs; swap to pdf/ for the direct PDF link
        pdf_url = abstract_url.replace('/abs/', '/pdf/') + ".pdf"

        content_hash = self.generate_content_hash(f"{title}|{abstract}")

        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=abstract_url,
            published_at=published_at,
            authors=authors,
            abstract=abstract,
            category=ContentCategory.PAPER.value,
            content_hash=content_hash,
            extra_data={"arxiv_id": arxiv_id, "pdf_url": pdf_url}
        )
