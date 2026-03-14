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

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Poll all feeds every 6 hours (21600 seconds)
    sender.add_periodic_task(21600.0, crawl_all_sources.s(), name='crawl every 6 hours')


@celery_app.task
def crawl_all_sources():
    sources = get_active_sources()
    for source in sources:
        crawl_source.delay(str(source.id))

@celery_app.task
def crawl_source(source_id: str):
    # This needs to run in an event loop because scrapers are async
    asyncio.run(_crawl_source_async(source_id))

@celery_app.task(rate_limit="1/s")
def enrich_arxiv_paper(url: str, arxiv_id: str):
    asyncio.run(_enrich_paper_async(url, arxiv_id))

async def _enrich_paper_async(url: str, arxiv_id: str):
    from athena.scrapers.semanticscholar import SemanticScholarEnricher
    from athena.scrapers.paperswithcode import PapersWithCodeEnricher
    from athena.database.operations import update_content_item_metrics
    
    ss_enricher = SemanticScholarEnricher()
    pwc_enricher = PapersWithCodeEnricher()
    
    logger.info(f"Enriching paper: {arxiv_id}")
    ss_data = await ss_enricher.fetch_paper_metrics(arxiv_id)
    pwc_data = await pwc_enricher.fetch_paper_artifacts(arxiv_id)
    
    citation_count = ss_data.get("citation_count", 0) if ss_data else 0
    extra_data = {
        "semantic_scholar": ss_data,
        "papers_with_code": pwc_data
    }
    
    update_content_item_metrics(url, citation_count, extra_data)

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
            new_urls = save_content_items(items)
            # Trigger enrichment for newly added arXiv papers
            if "arxiv" in source.url and new_urls:
                for item in items:
                    if str(item.url) in new_urls:
                        arxiv_id = item.extra_data.get("arxiv_id")
                        if arxiv_id:
                            enrich_arxiv_paper.delay(str(item.url), arxiv_id)
