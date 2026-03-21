import feedparser
import httpx
import html
from typing import List, Any
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger


class RSSScraper(BaseScraper):
    def __init__(self, source_id: str, source_category: str = "company"):
        super().__init__(source_id)
        self.source_category = source_category

    async def fetch(self, url: str) -> List[Any]:
        """Fetch raw RSS feed entries via HTTP."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, follow_redirects=True, timeout=30.0)
                response.raise_for_status()
                feed = feedparser.parse(response.text)
                return [(entry, url) for entry in feed.entries]
            except Exception as e:
                logger.error(f"Error fetching RSS from {url}: {e}")
                raise e

    def parse(self, raw: Any) -> ContentItemCreate:
        """Normalise a single RSS entry to ContentItemCreate."""
        entry, source_url = raw
        title = html.unescape((entry.get('title') or 'Unknown Title').strip())
        link = (entry.get('link') or '').strip()

        if not link:
            raise ValueError(f"RSS entry has no URL, cannot create ContentItemCreate: title='{title}'")

        # Robust date parsing: try RFC 2822 first, then struct_time, then UTC now
        published_at = self._parse_date(entry)

        authors = [a.get('name') for a in entry.get('authors', []) if a.get('name')]
        if not authors and entry.get('author'):
            authors = [entry.author]

        summary = html.unescape(entry.get('summary', entry.get('description', '')).strip())

        # Determine category based on stored source category
        category = (
            ContentCategory.COMPANY_BLOG.value
            if self.source_category == "company"
            else ContentCategory.COMMUNITY_BLOG.value
        )

        content_hash = self.generate_content_hash(f"{title}|{summary}")
        return ContentItemCreate(
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

    def _parse_date(self, entry) -> datetime:
        """Robust date parser that handles RFC 2822 strings and time.struct_time."""
        # 1. Try RFC 2822 string (most reliable, preserves timezone)
        for field in ('published', 'updated', 'created'):
            date_str = entry.get(field)
            if date_str:
                try:
                    return parsedate_to_datetime(date_str)
                except Exception:
                    pass
        # 2. Fall back to feedparser's struct_time (loses timezone info)
        for field in ('published_parsed', 'updated_parsed', 'created_parsed'):
            parsed = entry.get(field)
            if parsed:
                try:
                    import calendar
                    ts = calendar.timegm(parsed)  # interprets as UTC
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except Exception:
                    pass
        # 3. Final fallback: current UTC time
        return datetime.now(tz=timezone.utc)
