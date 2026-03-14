from celery import Celery
import os
import time
import asyncio
import hashlib
import redis as redis_lib
from typing import Optional
from dotenv import load_dotenv
from athena.database.operations import get_active_sources, save_content_items
from athena.scrapers.arxiv import ArXivScraper
from athena.scrapers.rss import RSSScraper
from athena.scrapers.scraping import PlaywrightScraper
from athena.scrapers.lesswrong import LessWrongScraper, AIAlignmentForumScraper
from athena.scrapers.substack import SubstackScraper
from athena.core.models import SourceType
from loguru import logger

load_dotenv()

celery_app = Celery(
    "athena",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

# Celery config: enable dead-letter queue via task_routes
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

DLQ_KEY = "athena:dlq"  # Redis list for permanently failed tasks


def _push_to_dlq(source_id: str, exc: Exception):
    """Push a permanently failed task to the dead-letter queue in Redis."""
    import json
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis_lib.from_url(redis_url)
    payload = json.dumps({"source_id": source_id, "error": str(exc), "ts": time.time()})
    r.rpush(DLQ_KEY, payload)
    logger.critical(f"[DLQ] Permanent failure for source {source_id}: {exc}")


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Poll all feeds every 6 hours (21600 seconds)
    sender.add_periodic_task(21600.0, crawl_all_sources.s(), name='crawl every 6 hours')


@celery_app.task
def crawl_all_sources():
    sources = get_active_sources()
    for source in sources:
        crawl_source.delay(str(source.id))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def crawl_source(self, source_id: str):
    try:
        asyncio.run(_crawl_source_async(source_id, is_retry=self.request.retries > 0))
    except Exception as exc:
        logger.error(f"Task for source {source_id} failed: {exc}")
        if self.request.retries >= self.max_retries:
            _push_to_dlq(source_id, exc)
            return  # Drop - already in DLQ, no more retries
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)


@celery_app.task(bind=True, max_retries=3, rate_limit="1/s")
def enrich_arxiv_paper(self, url: str, arxiv_id: str):
    try:
        asyncio.run(_enrich_paper_async(url, arxiv_id))
    except Exception as exc:
        logger.error(f"Enrichment task failed for {arxiv_id}: {exc}")
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


def _get_scraper(source, source_id: str):
    """Factory: return the right scraper for this source type and URL."""
    url = source.url
    stype = source.type

    if stype == SourceType.API:
        if "arxiv" in url:
            return ArXivScraper(source_id=source_id)
    elif stype == SourceType.RSS:
        cat = source.category.value if hasattr(source.category, 'value') else str(source.category)
        return RSSScraper(source_id=source_id, source_category=cat)
    elif stype == SourceType.SCRAPE:
        # Route to API-based scrapers where possible to avoid fragile headless browser
        if "lesswrong" in url:
            return LessWrongScraper(source_id=source_id)
        elif "alignmentforum" in url:
            return AIAlignmentForumScraper(source_id=source_id)
        elif "substack" in url:
            return SubstackScraper(source_id=source_id)
        else:
            return PlaywrightScraper(source_id=source_id)
    return None


async def _crawl_source_async(source_id: str, is_retry: bool = False):
    from athena.database.db import SessionLocal
    from athena.core.models import Source, FetchLog, QuarantineItem
    from sqlalchemy import select

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
        new_urls = []
        error_msg = None
        status = "success"

        try:
            scraper = _get_scraper(source, source_id)
            if scraper is None:
                logger.warning(f"No scraper configured for {source.name}. Skipping.")
                return

            # Use the BaseScraper.run() orchestrator (fetch + parse per item)
            # This allows per-item Pydantic validation errors to be quarantined
            raw_items = await scraper.fetch(source.url) if source.type != SourceType.API else await scraper.fetch()

            for raw in raw_items:
                try:
                    item = scraper.parse(raw)
                    items.append(item)
                except Exception as parse_err:
                    logger.warning(f"Pydantic/parse error for item from {source.name}: {parse_err}")
                    # Quarantine the bad record for later inspection
                    try:
                        q = QuarantineItem(
                            source_id=source.id,
                            raw_data=str(raw)[:2000] if raw else None,
                            error_message=str(parse_err)[:500]
                        )
                        session.add(q)
                    except Exception:
                        pass

            if items:
                new_urls = save_content_items(items)
                if new_urls:
                    for item in items:
                        item_url = str(item.url)
                        if item_url in new_urls:
                            if "arxiv" in source.url:
                                arxiv_id = item.extra_data.get("arxiv_id")
                                if arxiv_id:
                                    enrich_arxiv_paper.delay(item_url, arxiv_id)
                            # Phase 5: Stage and queue
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
                    logger.critical(f"[ALERT] Source '{source.name}' DEACTIVATED after 5 consecutive failures!")

            raise e

        finally:
            duration_ms = (time.time() - start_time) * 1000
            if not (is_retry and status == "error"):
                log_entry = FetchLog(
                    source_id=source.id,
                    status=status,
                    error_message=error_msg,
                    duration_ms=duration_ms,
                    items_fetched=len(new_urls)
                )
                session.add(log_entry)

            from datetime import datetime
            source.last_fetched_at = datetime.utcnow()
            session.commit()


@celery_app.task(bind=True, max_retries=2)
def stage_content_item(self, url: str, text: str, title: str, item_id: Optional[str] = None):
    """
    Phase 5: Write full text to staging directory, update ContentItem.full_text_path,
    and push the item UUID onto the Redis embedding queue.
    """
    import os
    from sqlalchemy import update, select
    from athena.database.db import SessionLocal
    from athena.core.models import ContentItem

    staging_dir = "/tmp/athena/staging"
    os.makedirs(staging_dir, exist_ok=True)

    try:
        # Use item_id as filename if provided, else fall back to URL hash
        identifier = item_id if item_id else hashlib.sha256(url.encode()).hexdigest()[:16]
        file_path = os.path.join(staging_dir, f"{identifier}.txt")

        # Write preprocessed text to disk
        clean_text = _preprocess_text(title + "\n\n" + text)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_text)

        # Update full_text_path back on the ContentItem record
        with SessionLocal() as session:
            item = session.execute(
                select(ContentItem).where(ContentItem.url == url)
            ).scalar_one_or_none()
            if item:
                session.execute(
                    update(ContentItem).where(ContentItem.url == url).values(
                        full_text_path=file_path
                    )
                )
                session.commit()
                identifier = str(item.id)  # Use the real DB UUID for the queue

        # Push the UUID onto the Redis embedding queue
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis_lib.from_url(redis_url)
        r.rpush("athena:embedding_queue", identifier)
        logger.info(f"Staged item to {file_path}, updated DB, and queued UUID {identifier}.")
    except Exception as exc:
        logger.error(f"Staging failed for {url}: {exc}")
        raise self.retry(exc=exc, countdown=30)


def _preprocess_text(text: str, max_chars: int = 8000) -> str:
    """Strip HTML tags, normalize whitespace, and truncate to token limit."""
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:max_chars]
