from celery import Celery
import os
from dotenv import load_dotenv
from athena.database.operations import get_active_sources, save_content_items
from athena.scrapers.arxiv import ArXivScraper
from athena.scrapers.rss import RSSScraper
from athena.scrapers.scraping import PlaywrightScraper
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

import time

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def crawl_source(self, source_id: str):
    try:
        # We run the async logic, catching specific failures inside
        asyncio.run(_crawl_source_async(source_id, is_retry=self.request.retries > 0))
    except Exception as exc:
        logger.error(f"Task for source {source_id} failed with {exc}")
        if self.request.retries >= self.max_retries:
            logger.error(f"Permanent failure for source {source_id}. Task dropped to dead-letter log.")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60) # Exponential backoff

@celery_app.task(bind=True, max_retries=3, rate_limit="1/s")
def enrich_arxiv_paper(self, url: str, arxiv_id: str):
    try:
        asyncio.run(_enrich_paper_async(url, arxiv_id))
    except Exception as exc:
        logger.error(f"Enrichment task failed for {arxiv_id}")
        raise self.retry(exc=exc, countdown=60)

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

async def _crawl_source_async(source_id: str, is_retry: bool = False):
    from athena.database.db import SessionLocal
    from athena.core.models import Source, FetchLog
    from sqlalchemy import select, update
    import traceback

    with SessionLocal() as session:
        source = session.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if not source:
            logger.error(f"Source {source_id} not found.")
            return
            
        if not source.is_active:
            logger.warning(f"Source {source.name} is inactive. Skipping.")
            return

        logger.info(f"Crawling source: {source.name} ({source.url})")
        start_time = time.time()
        
        items = []
        error_msg = None
        status = "success"
        
        try:
            if source.type == SourceType.API:
                if "arxiv" in source.url:
                    scraper = ArXivScraper(source_id=source_id)
                    items = await scraper.fetch()
            elif source.type == SourceType.RSS:
                scraper = RSSScraper(source_id=source_id)
                items = await scraper.fetch(source.url)
            elif source.type == SourceType.SCRAPE:
                scraper = PlaywrightScraper(source_id=source_id)
                items = await scraper.fetch(source.url)
            
            if items:
                new_urls = save_content_items(items)
                if new_urls:
                    # Trigger enrichment for new arXiv papers and stage ALL new items
                    for item in items:
                        item_url = str(item.url)
                        if item_url in new_urls:
                            # Enrichment: arXiv only
                            if "arxiv" in source.url:
                                arxiv_id = item.extra_data.get("arxiv_id")
                                if arxiv_id:
                                    enrich_arxiv_paper.delay(item_url, arxiv_id)
                            # Phase 5: Stage content to disk and push to embedding queue
                            stage_content_item.delay(item_url, item.abstract or '', item.title)
                                
            # Reset consecutive failures on success
            source.consecutive_failures = 0
            
        except Exception as e:
            error_msg = str(e)
            status = "error"
            logger.error(f"Error crawling {source.name}: {error_msg}")
            
            if not is_retry:
                source.consecutive_failures += 1
                if source.consecutive_failures >= 5:
                    source.is_active = False
                    logger.critical(f"Source {source.name} deactivated after 5 consecutive failures.")
                    
            # We must raise to trigger Celery retry
            raise e
            
        finally:
            duration_ms = (time.time() - start_time) * 1000
            if is_retry and status == "error":
                # We skip duplicating logs for every retry attempt to keep fetch_logs clean, 
                # but log the final structure
                pass
            else:
                log_entry = FetchLog(
                    source_id=source.id,
                    status=status,
                    error_message=error_msg,
                    duration_ms=duration_ms
                )
                session.add(log_entry)
            
            from datetime import datetime
            source.last_fetched_at = datetime.utcnow()
            session.commit()

@celery_app.task(bind=True, max_retries=2)
def stage_content_item(self, url: str, text: str, title: str):
    """
    Phase 5: Write full text to staging directory and push item_id to the Redis embedding queue.
    """
    import hashlib, os, redis
    staging_dir = "/tmp/athena/staging"
    os.makedirs(staging_dir, exist_ok=True)

    try:
        # Create a stable filename from the URL hash
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        file_path = os.path.join(staging_dir, f"{url_hash}.txt")

        # Write preprocessed text to disk
        clean_text = _preprocess_text(title + "\n\n" + text)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_text)

        # Push the url_hash (item identifier) onto the Redis embedding queue
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.rpush("athena:embedding_queue", url_hash)
        logger.info(f"Staged item to {file_path} and queued {url_hash} for embedding.")
    except Exception as exc:
        logger.error(f"Staging failed for {url}: {exc}")
        raise self.retry(exc=exc, countdown=30)

def _preprocess_text(text: str, max_chars: int = 8000) -> str:
    """Strip HTML tags, normalize whitespace, and truncate to token limit."""
    import re
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    # Truncate to token limit (approx 4 chars/token for 2000 token limit)
    return clean[:max_chars]
