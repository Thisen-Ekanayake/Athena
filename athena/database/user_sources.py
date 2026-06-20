"""
User-Managed Source Utilities (Section 8 of the acquisition plan).

Provides:
- detect_source_type(url) -> SourceType
- add_user_source(url, name) -> Source (test-fetches, confirms, saves, queues first crawl)
"""
from typing import Optional
from loguru import logger

import feedparser
import httpx

from athena.core.models import SourceType


def detect_source_type(url: str) -> SourceType:
    """
    Auto-detect the source type given any URL.
    Logic per Section 8.2 of the acquisition plan:
    1. Try fetching as RSS/Atom
    2. Check known API patterns
    3. Default to SCRAPE (Playwright)
    """
    url = url.strip()

    # 2. Known API patterns
    if 'arxiv.org' in url:
        return SourceType.API
    if 'semanticscholar.org' in url:
        return SourceType.API
    if 'lesswrong.com' in url or 'alignmentforum.org' in url:
        return SourceType.SCRAPE  # Will use GraphQL API in scraper factory

    # 1. Try fetching as RSS
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url)
            content_type = resp.headers.get('Content-Type', '')
            if 'xml' in content_type or 'rss' in content_type or 'atom' in content_type:
                return SourceType.RSS
            # Try feedparser parse regardless
            feed = feedparser.parse(resp.text)
            if feed.entries:
                return SourceType.RSS
    except Exception:
        pass

    # 3. Default to SCRAPE
    return SourceType.SCRAPE


def _derive_name(url: str) -> str:
    """Best-effort human-friendly source name from a URL."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or url).strip()
    return host[4:] if host.startswith("www.") else host


def preview_source(url: str, name: Optional[str] = None) -> dict:
    """
    Perform a test fetch and return a preview of what data would be retrieved.
    Used to let users confirm before a source is added.

    Returns a payload shaped for the frontend:
        {source_type, source_name, sample_items: [{title, url, published_at, summary}]}
    On a hard failure (e.g. the URL cannot be reached) returns {"error": ...}
    so the caller can surface a 400.
    """
    from athena.scrapers.rss import RSSScraper
    import asyncio

    source_type = detect_source_type(url)
    source_name = name or _derive_name(url)

    # Create a temporary dummy source_id for preview
    dummy_id = "00000000-0000-0000-0000-000000000000"

    sample_items: list[dict] = []
    try:
        if source_type == SourceType.RSS:
            scraper = RSSScraper(source_id=dummy_id)
            raws = asyncio.run(scraper.fetch(url))
            for raw in raws[:3]:
                item = scraper.parse(raw)
                sample_items.append({
                    "title": str(item.title),
                    "url": str(item.url),
                    "published_at": (
                        item.published_at.isoformat()
                        if item.published_at else None
                    ),
                    "summary": item.abstract,
                })
        # API and SCRAPE sources can't be cheaply previewed; we still let the
        # user add them — the first crawl runs in the background once confirmed.
    except Exception as e:
        return {
            "source_type": source_type.value,
            "source_name": source_name,
            "sample_items": [],
            "error": str(e),
        }

    return {
        "source_type": source_type.value,
        "source_name": source_name,
        "sample_items": sample_items,
    }


def add_user_source(url: str, name: Optional[str] = None, category: str = "blog") -> dict:
    """
    Add a user-managed source:
    1. Auto-detect type
    2. Preview fetch
    3. Upsert into sources table with added_by='user'
    4. Queue the first crawl immediately
    """
    from athena.core.schemas import SourceCreate
    from athena.core.models import SourceCategory
    from athena.pipeline.tasks import crawl_source

    source_type = detect_source_type(url)

    # Map category string to enum
    try:
        cat_enum = SourceCategory(category.lower())
    except ValueError:
        cat_enum = SourceCategory.BLOG

    source_name = name or url

    source_data = SourceCreate(
        name=source_name,
        url=url,
        type=source_type,
        category=cat_enum,
        fetch_config={},
        is_active=True,
    )
    # Patch added_by to 'user'
    data = source_data.dict()
    data['added_by'] = 'user'
    data['url'] = str(data['url'])

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from athena.database.db import SessionLocal
    from athena.core.models import Source
    from sqlalchemy import select

    with SessionLocal() as session:
        stmt = pg_insert(Source).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['url'],
            set_={k: v for k, v in data.items() if k != 'url'}
        )
        session.execute(stmt)
        session.commit()
        source = session.execute(select(Source).where(Source.url == data['url'])).scalar_one()
        source_id = str(source.id)

    # Queue first crawl immediately. A broker outage shouldn't fail the add —
    # the source is saved and the periodic crawl will pick it up regardless.
    queued = True
    try:
        crawl_source.delay(source_id)
        logger.info(f"User source '{source_name}' added ({source_type}) and queued for first crawl.")
    except Exception as e:
        queued = False
        logger.warning(f"User source '{source_name}' added ({source_type}) but first crawl could not be queued: {e}")

    return {
        "id": source_id,
        "name": source_name,
        "type": source_type.value,
        "queued": queued
    }
