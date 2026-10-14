from athena.pipeline.celery_app import celery_app
import os
import time
import asyncio
import hashlib
import re
from typing import Optional
from athena.database.operations import get_active_sources, save_content_items
from athena.scrapers.arxiv import ArXivScraper
from athena.scrapers.rss import RSSScraper
from athena.scrapers.scraping import PlaywrightScraper
from athena.scrapers.lesswrong import LessWrongScraper, AIAlignmentForumScraper
from athena.scrapers.substack import SubstackScraper
from athena.core.models import SourceType
from athena.core.redis_client import get_redis
from loguru import logger
import athena.pipeline.embedding_worker
import athena.pipeline.clustering
import athena.pipeline.scoring
import athena.pipeline.summarisation_tasks  # noqa: F401  (registers the summary tasks with every worker)
import athena.evolution.tasks  # noqa: F401  (registers the evolution queue's tasks)
import athena.pipeline.watches  # noqa: F401  (registers the watch checks and digests)
import athena.pipeline.momentum  # noqa: F401  (registers the daily citation momentum)
from athena.core.logging import setup_redis_logging

# Staging directory for full-text files (configurable via env; defaults to persistent
# /var/lib path so that container restarts don't wipe pending work).
STAGING_DIR = os.getenv("ATHENA_STAGING_DIR", "/var/lib/athena/staging")

# Initialize Redis logging sink for live sync feedback
setup_redis_logging()

# Celery config: enable dead-letter queue via task_routes

DLQ_KEY = "athena:dlq"  # Redis list for permanently failed tasks


def _push_to_dlq(source_id: str, exc: Exception):
    """Push a permanently failed task to the dead-letter queue in Redis."""
    import json
    r = get_redis()
    payload = json.dumps({"source_id": source_id, "error": str(exc), "ts": time.time()})
    r.rpush(DLQ_KEY, payload)
    logger.critical(f"[DLQ] Permanent failure for source {source_id}: {exc}")


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Poll all feeds every 6 hours (21600 seconds)
    sender.add_periodic_task(21600.0, crawl_all_sources.s(), name='crawl every 6 hours')
    # Run embedding worker every 1 minute
    sender.add_periodic_task(
        60.0,
        athena.pipeline.embedding_worker.process_embedding_queue.s(),
        name='process embeddings every 1 minute')
    # Run clustering every 6 hours
    sender.add_periodic_task(
        21600.0,
        athena.pipeline.clustering.run_clustering.s(),
        name='run clustering every 6 hours')
    # Run item linking every 6 hours (after clustering)
    sender.add_periodic_task(
        21600.0,
        athena.pipeline.clustering.compute_item_links.s(),
        name='compute links every 6 hours')
    # Run scoring queue every 1 minute
    sender.add_periodic_task(60.0, athena.pipeline.scoring.process_scoring_queue.s(),
                             name='process scoring queue every 1 minute')
    # Refresh recency scores every 6 hours
    sender.add_periodic_task(21600.0,
                             athena.pipeline.scoring.refresh_recency_scores.s(),
                             name='refresh recency scores every 6 hours')
    # Citation counts, metric snapshots and 7/30-day gains: checked hourly, done once per UTC day (a 24 h interval
    # restarts its clock with beat and never fired on machines that restart often)
    sender.add_periodic_task(3600.0, athena.pipeline.momentum.daily_momentum.s(), name='daily citation momentum')
    # Hourly summaries: every item without one, highest score first
    sender.add_periodic_task(3600.0, enqueue_tier2_summaries.s(), name='hourly tier 2 summaries')
    # Daily trending briefs per category
    sender.add_periodic_task(86400.0, generate_all_trending_briefs.s(), name='daily trending briefs')
    # Feed papers that are in a map, or cite a map's milestones
    sender.add_periodic_task(21600.0, athena.evolution.tasks.link_feed.s(), name='link the feed to the maps')
    # Nightly: refresh the evolution maps whose last build is older than their interval
    from celery.schedules import crontab
    from athena.evolution.refresh import REFRESH_HOUR_UTC
    sender.add_periodic_task(crontab(hour=REFRESH_HOUR_UTC, minute=0), athena.evolution.tasks.refresh_due_topics.s(),
                             name='refresh evolution maps')
    # Follows: searches, sources and clusters against new feed items; daily digests after the map refresh
    sender.add_periodic_task(3600.0, athena.pipeline.watches.check_watches.s(), name='check watches every hour')
    sender.add_periodic_task(crontab(hour=athena.pipeline.watches.DIGEST_HOUR_UTC, minute=0),
                             athena.pipeline.watches.send_digests.s(), name='inbox digests')
    # The month's model spend against its budget: admins hear at 80% and 100%
    sender.add_periodic_task(3600.0, check_model_budget.s(), name='check the model budget every hour')


@celery_app.task
def check_model_budget():
    """Tell the admins, once a month each, when model spend passes 80% and then 100% of the monthly budget."""
    from athena.core import usage
    from athena.database.db import SessionLocal
    usage.flush()  # this worker's own background calls count too
    with SessionLocal() as session:
        threshold = usage.budget_alerts(session)
        session.commit()
    return threshold


@celery_app.task
def generate_all_trending_briefs():
    """Trigger daily trending brief generation for all categories."""
    import athena.pipeline.summarisation_tasks
    from athena.core.models import ContentCategory

    for cat in ContentCategory:
        athena.pipeline.summarisation_tasks.generate_trending_brief_worker.apply_async(
            args=[cat.value], queue='summary_trend'
        )


SUMMARY_BATCH = 500                 # the hourly run tops the queue up to this many jobs, highest score first
SUMMARY_QUEUED_TTL = 6 * 3600       # an item queued this recently is not queued again


@celery_app.task
def enqueue_tier2_summaries():
    """Hourly: queue a summary for every item that has none, highest score first.

    Items scoring under 0.40 used to wait to be summarised when opened, but nothing in the app asked, so they
    never got one; now they follow the better items. Items skipped for having too little text are left out.
    One worker summarises a few hundred items an hour, so the run only tops the queue up to SUMMARY_BATCH,
    and a short-lived Redis marker keeps an item from being queued twice.
    """
    from sqlalchemy import or_
    from athena.database.db import SessionLocal
    from athena.core.models import ContentItem, SummaryStatus
    import athena.pipeline.summarisation_tasks

    # Only enqueue if we have budget
    from athena.pipeline.summarisation import check_budget_before_call
    if not check_budget_before_call("item_summary"):
        logger.warning('Budget exhausted, skipping the hourly summary batch')
        return

    r = get_redis()
    room = SUMMARY_BATCH - r.llen("summary_standard")
    if room <= 0:
        logger.info("The summary queue is still full; nothing queued this hour.")
        return
    queued = 0
    with SessionLocal() as session:
        items = session.query(ContentItem).filter(
            ContentItem.summary_status != SummaryStatus.COMPLETE,
            or_(ContentItem.extra_data.is_(None), ~ContentItem.extra_data.has_key("summary_skipped")),
        ).order_by(ContentItem.score.desc().nulls_last()).limit(room * 2).all()

        for item in items:
            if queued >= room:
                break
            if not r.set(f"summary:queued:{item.id}", 1, nx=True, ex=SUMMARY_QUEUED_TTL):
                continue  # an earlier job for it is still waiting
            item.summary_status = SummaryStatus.PENDING
            athena.pipeline.summarisation_tasks.summarise_item_worker.apply_async(
                args=[str(item.id)], queue='summary_standard')
            queued += 1
        session.commit()
    logger.info(f"Queued {queued} items for summarisation.")


def _publish_sync_event(payload: dict):
    """Publish a structured sync progress event to Redis."""
    import json
    from athena.core.logging import SYNC_LOG_CHANNEL
    try:
        r = get_redis()
        r.publish(SYNC_LOG_CHANNEL, json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish sync event: {e}")


def _publish_crawl_progress(status: str):
    """Increment the sync counter and emit progress/done events."""
    try:
        r = get_redis()
        if not r.exists('athena:sync:state'):
            return

        r.hincrby('athena:sync:state', 'completed', 1)
        if status == 'error':
            r.hincrby('athena:sync:state', 'errors', 1)

        state = {k.decode(): v.decode() for k, v in r.hgetall('athena:sync:state').items()}
        completed = int(state.get('completed', 0))
        total = int(state.get('total', 0))
        errors = int(state.get('errors', 0))

        _publish_sync_event({'type': 'sync_progress', 'completed': completed, 'total': total})

        if total > 0 and completed >= total:
            overall = 'error' if errors == total else ('partial' if errors > 0 else 'done')
            _publish_sync_event({
                'type': 'sync_done',
                'status': overall,
                'completed': completed,
                'errors': errors,
                'total': total,
            })
            r.delete('athena:sync:state')
    except Exception as e:
        logger.warning(f"Failed to publish crawl progress: {e}")


@celery_app.task
def crawl_all_sources():
    logger.info("Starting manual sync of all sources...")
    sources = get_active_sources()
    if not sources:
        logger.warning("No active sources found to sync!")
        return

    total = len(sources)
    try:
        r = get_redis()
        r.hset('athena:sync:state', mapping={'total': total, 'completed': 0, 'errors': 0})
        r.expire('athena:sync:state', 7200)
        _publish_sync_event({'type': 'sync_start', 'total': total})
    except Exception as e:
        logger.warning(f"Failed to initialise sync state: {e}")

    logger.info(f"Found {total} active sources. Enqueueing crawl tasks...")
    for source in sources:
        crawl_source.delay(str(source.id))
    logger.info("All crawl tasks have been enqueued.")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def crawl_source(self, source_id: str):
    try:
        asyncio.run(_crawl_source_async(source_id, is_retry=self.request.retries > 0))
        _publish_crawl_progress('success')
    except Exception as exc:
        logger.error(f"Task for source {source_id} failed: {exc}")
        if self.request.retries >= self.max_retries:
            _push_to_dlq(source_id, exc)
            _publish_crawl_progress('error')
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

    # Strip version suffix (e.g. 2403.00001v1 -> 2403.00001) as enrichment APIs prefer base IDs
    base_arxiv_id = re.sub(r'v\d+$', '', arxiv_id)

    logger.info(f"Enriching paper: {base_arxiv_id} (original: {arxiv_id})")
    ss_data = await ss_enricher.fetch_paper_metrics(base_arxiv_id)
    pwc_data = await pwc_enricher.fetch_paper_artifacts(base_arxiv_id)

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
                logger.info(f"Parsed {len(items)} items from {source.name}. Saving new items...")
                new_urls = save_content_items(items)
                if new_urls:
                    logger.success(f"Added {len(new_urls)} new items from {source.name}!")
                    for item in items:
                        item_url = str(item.url)
                        if item_url in new_urls:
                            if "arxiv" in source.url:
                                arxiv_id = item.extra_data.get("arxiv_id")
                                if arxiv_id:
                                    enrich_arxiv_paper.delay(item_url, arxiv_id)
                            # Phase 5: Stage and queue
                            stage_content_item.delay(item_url, item.abstract or '', item.title)
                else:
                    logger.info(f"No new items found for {source.name} (all {len(items)} items were duplicates).")
            else:
                logger.warning(f"No items were correctly parsed from {source.name}.")

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
    from sqlalchemy import update, select
    from athena.database.db import SessionLocal
    from athena.core.models import ContentItem

    try:
        os.makedirs(STAGING_DIR, exist_ok=True)
    except OSError as mkdir_err:
        # Fall back to /tmp if the configured dir isn't writable (e.g. dev machines
        # where /var/lib/athena doesn't exist). Emit a warning so ops can fix it.
        fallback = "/tmp/athena/staging"
        logger.warning(
            f"Staging dir {STAGING_DIR!r} not writable ({mkdir_err}); "
            f"falling back to {fallback!r}"
        )
        os.makedirs(fallback, exist_ok=True)
        staging_dir = fallback
    else:
        staging_dir = STAGING_DIR

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
        r = get_redis()
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
