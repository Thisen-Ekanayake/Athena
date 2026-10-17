import httpx
import xml.etree.ElementTree as ET
import asyncio
import time
from typing import List, Any
from datetime import datetime, timedelta, timezone
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger

# The arXiv categories the feed follows. Each needs its cat: prefix: a bare stat.ML searched every field for that
# text instead of the category. A source's fetch_config "query" replaces this.
ARXIV_DEFAULT_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:stat.ML"
ARXIV_DEFAULT_MAX_RESULTS = 50
# A sync takes every paper since the newest one stored, up to this many (a source's fetch_config "max_results");
# the categories get several hundred a day, and the newest 50 alone missed most of them.
ARXIV_MAX_PER_SYNC = 1000
# ...and looks this far behind it: arXiv lists papers by submission time, and one held for moderation is announced
# days after newer ones. Papers already stored are skipped when they are saved.
ARXIV_LOOKBACK = timedelta(days=2)
ARXIV_PAGE_SIZE = 200
ARXIV_PAGE_DELAY = 3.0  # seconds between pages, as arXiv's API terms ask

# Global state to enforce 3 req/s limit across all ArXivScraper instances in this process
_LAST_ARXIV_CALL_TIME = 0.0
_ARXIV_LOCK = asyncio.Lock()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def sync_args(fetch_config: dict | None, newest: datetime | None) -> dict:
    """What a sync asks arXiv for: the source's query and limit (or the defaults), back to ARXIV_LOOKBACK before
    the newest paper stored (or the newest page, for a source with none yet)."""
    config = fetch_config or {}
    try:
        limit = int(config.get("max_results") or ARXIV_MAX_PER_SYNC)
    except (TypeError, ValueError):
        limit = ARXIV_MAX_PER_SYNC
    return {"search_query": config.get("query") or ARXIV_DEFAULT_QUERY, "max_results": max(1, limit),
            "since": _aware(newest) - ARXIV_LOOKBACK if newest else None}


class ArXivScraper(BaseScraper):
    BASE_URL = "https://export.arxiv.org/api/query"
    NAMESPACE = {'atom': 'http://www.w3.org/2005/Atom'}

    async def fetch(self, search_query: str = ARXIV_DEFAULT_QUERY,
                    max_results: int = ARXIV_DEFAULT_MAX_RESULTS,
                    since: datetime | None = None) -> List[Any]:
        """The newest papers as Atom XML entries, newest first.

        Without ``since``, the newest ``max_results``. With it, pages back until papers published before
        ``since`` (the newest one already stored), stopping at ``max_results``.
        """
        entries: List[Any] = []
        async with httpx.AsyncClient() as client:
            while len(entries) < max_results:
                size = min(ARXIV_PAGE_SIZE, max_results - len(entries))
                if entries:
                    await asyncio.sleep(ARXIV_PAGE_DELAY)
                page = await self._page(client, search_query, len(entries), size)
                if not page and entries:
                    # arXiv now and then answers a deep page with nothing; one more try before stopping
                    await asyncio.sleep(ARXIV_PAGE_DELAY)
                    page = await self._page(client, search_query, len(entries), size)
                if not page:
                    break
                for entry in page:
                    if since is not None and self._published(entry) < _aware(since):
                        return entries
                    entries.append(entry)
                if since is None:
                    break  # one page is all a plain fetch asks for
        return entries[:max_results]

    async def _page(self, client: httpx.AsyncClient, search_query: str, start: int, size: int) -> List[Any]:
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": size,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        }
        try:
            global _LAST_ARXIV_CALL_TIME
            async with _ARXIV_LOCK:
                now = time.time()
                elapsed = now - _LAST_ARXIV_CALL_TIME
                if elapsed < 0.34:  # 3 requests per second limit
                    await asyncio.sleep(0.34 - elapsed)

                response = await client.get(self.BASE_URL, params=params, timeout=30.0)
                _LAST_ARXIV_CALL_TIME = time.time()

            response.raise_for_status()
            root = ET.fromstring(response.text)
            return root.findall('atom:entry', self.NAMESPACE)
        except Exception as e:
            logger.error(f"Error fetching from ArXiv: {e!r}")
            raise e

    def _published(self, entry: Any) -> datetime:
        published = entry.find('atom:published', self.NAMESPACE).text.strip()
        return datetime.fromisoformat(published.replace('Z', '+00:00'))

    def parse(self, entry: Any) -> ContentItemCreate:
        """Normalise a single arXiv Atom XML entry to ContentItemCreate."""
        ns = self.NAMESPACE

        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        abstract_url = entry.find('atom:id', ns).text.strip()
        published_at = self._published(entry)

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
