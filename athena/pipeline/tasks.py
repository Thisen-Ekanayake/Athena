from celery import Celery
import os
from dotenv import load_dotenv
from athena.database.operations import get_active_sources, save_content_items
from athena.scrapers.arxiv import ArXivScraper
from athena.scrapers.rss import RSSScraper
from athena.core.models import SourceType
from loguru import logger
import asyncio

load_dotenv()

celery_app = Celery(
    "athena",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

@celery_app.task
def crawl_all_sources():
    sources = get_active_sources()
    for source in sources:
        crawl_source.delay(str(source.id))

@celery_app.task
def crawl_source(source_id: str):
    # This needs to run in an event loop because scrapers are async
    asyncio.run(_crawl_source_async(source_id))

async def _crawl_source_async(source_id: str):
    from athena.database.db import SessionLocal
    from athena.core.models import Source
    from sqlalchemy import select

    with SessionLocal() as session:
        source = session.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if not source:
            logger.error(f"Source {source_id} not found.")
            return

        logger.info(f"Crawling source: {source.name} ({source.url})")
        
        items = []
        if source.type == SourceType.API:
            if "arxiv" in source.url:
                scraper = ArXivScraper(source_id=source_id)
                items = await scraper.fetch()
        elif source.type == SourceType.RSS:
            scraper = RSSScraper(source_id=source_id)
            items = await scraper.fetch(source.url)
        
        if items:
            save_content_items(items)
