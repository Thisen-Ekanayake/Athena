import feedparser
import httpx
from typing import List
from datetime import datetime
import time
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger

class RSSScraper(BaseScraper):
    async def fetch(self, url: str) -> List[ContentItemCreate]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                return self.parse_feed(response.text, url)
            except Exception as e:
                logger.error(f"Error fetching RSS from {url}: {e}")
                return []

    def parse_feed(self, feed_content: str, source_url: str) -> List[ContentItemCreate]:
        feed = feedparser.parse(feed_content)
        items = []

        for entry in feed.entries:
            try:
                title = entry.get('title', 'Unknown Title').strip()
                link = entry.get('link', '').strip()
                
                # Handling different date fields in RSS/Atom
                published_parsed = entry.get('published_parsed') or entry.get('updated_parsed') or entry.get('created_parsed')
                if published_parsed:
                    published_at = datetime.fromtimestamp(time.mktime(published_parsed))
                else:
                    published_at = datetime.utcnow()

                authors = [author.get('name') for author in entry.get('authors', []) if author.get('name')]
                if not authors and entry.get('author'):
                    authors = [entry.author]

                summary = entry.get('summary', entry.get('description', '')).strip()
                
                content_hash = self.generate_content_hash(f"{title}|{summary}")

                # Determine category based on source (could be refined)
                category = ContentCategory.COMPANY_BLOG.value if "company" in source_url else ContentCategory.COMMUNITY_BLOG.value

                item = ContentItemCreate(
                    source_id=self.source_id,
                    title=title,
                    url=link,
                    published_at=published_at,
                    authors=authors,
                    abstract=summary[:500] if summary else None,
                    category=category,
                    content_hash=content_hash,
                    extra_data={"feed_link": source_url}
                )
                items.append(item)
            except Exception as e:
                logger.error(f"Error parsing RSS entry: {e}")
                continue

        return items
