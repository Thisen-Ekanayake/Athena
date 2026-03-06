import httpx
import xml.etree.ElementTree as ET
from typing import List
from datetime import datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate, ContentItemBase
from athena.core.models import ContentCategory
from loguru import logger

class ArXivScraper(BaseScraper):
    BASE_URL = "https://export.arxiv.org/api/query"

    async def fetch(self, search_query: str = "cat:cs.AI OR cat:cs.LG", max_results: int = 10) -> List[ContentItemCreate]:
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                return self.parse_response(response.text)
            except Exception as e:
                logger.error(f"Error fetching from ArXiv: {e}")
                return []

    def parse_response(self, xml_content: str) -> List[ContentItemCreate]:
        root = ET.fromstring(xml_content)
        namespace = {'atom': 'http://www.w3.org/2005/Atom'}
        items = []

        for entry in root.findall('atom:entry', namespace):
            try:
                title = entry.find('atom:title', namespace).text.strip().replace('\n', ' ')
                url = entry.find('atom:id', namespace).text.strip()
                published_str = entry.find('atom:published', namespace).text.strip()
                published_at = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                
                authors = [author.find('atom:name', namespace).text for author in entry.findall('atom:author', namespace)]
                abstract = entry.find('atom:summary', namespace).text.strip()
                
                content_hash = self.generate_content_hash(f"{title}|{abstract}")

                item = ContentItemCreate(
                    source_id=self.source_id,
                    title=title,
                    url=url,
                    published_at=published_at,
                    authors=authors,
                    abstract=abstract,
                    category=ContentCategory.PAPER.value,
                    content_hash=content_hash,
                    extra_data={"arxiv_id": url.split('/')[-1]}
                )
                items.append(item)
            except Exception as e:
                logger.error(f"Error parsing ArXiv entry: {e}")
                continue

        return items
