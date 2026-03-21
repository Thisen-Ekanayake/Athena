"""
Generic Substack RSS Harvester.
Substack blogs publish RSS feeds at: https://<blog>.substack.com/feed
This scraper accepts any Substack URL and constructs the RSS feed URL automatically.
"""
import httpx
import feedparser
import html
from typing import List, Any
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger


def detect_substack_feed(url: str) -> str:
    """
    Given a Substack URL (e.g. https://gradientflow.substack.com or
    https://gradientflow.substack.com/p/some-post), return the RSS feed URL.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return f"{base}/feed"


class SubstackScraper(BaseScraper):
    """
    Generic Substack RSS harvester.
    `url` should be the base Substack URL (e.g. https://gradientflow.substack.com).
    Feed URL is auto-constructed as <base>/feed.
    """

    async def fetch(self, url: str) -> List[Any]:
        feed_url = detect_substack_feed(url)
        logger.info(f"Fetching Substack RSS: {feed_url}")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(feed_url, follow_redirects=True, timeout=30.0)
                response.raise_for_status()
                feed = feedparser.parse(response.text)
                return [(entry, url) for entry in feed.entries]
            except Exception as e:
                logger.error(f"Error fetching Substack feed {feed_url}: {e}")
                raise e

    def parse(self, raw: Any) -> ContentItemCreate:
        entry, source_url = raw
        title = html.unescape(entry.get('title', 'Unknown').strip())
        link = entry.get('link', '').strip()

        # Robust date parsing
        published_at = self._parse_date(entry)

        authors = [a.get('name') for a in entry.get('authors', []) if a.get('name')]
        if not authors and entry.get('author'):
            authors = [entry.author]

        summary = html.unescape(entry.get('summary', entry.get('description', '')).strip())

        content_hash = self.generate_content_hash(f"{title}|{summary}")
        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=link,
            published_at=published_at,
            authors=authors,
            abstract=summary[:800] if summary else None,
            category=ContentCategory.COMMUNITY_BLOG.value,
            content_hash=content_hash,
            extra_data={"feed_source": source_url, "platform": "substack"}
        )

    def _parse_date(self, entry) -> datetime:
        for field in ('published', 'updated', 'created'):
            date_str = entry.get(field)
            if date_str:
                try:
                    return parsedate_to_datetime(date_str)
                except Exception:
                    pass
        for field in ('published_parsed', 'updated_parsed', 'created_parsed'):
            parsed = entry.get(field)
            if parsed:
                try:
                    import calendar
                    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
                except Exception:
                    pass
        return datetime.now(tz=timezone.utc)
