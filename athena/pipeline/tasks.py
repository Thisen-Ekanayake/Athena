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


def _push_to_dlq(source_id: str, error: str):
    """Push a permanently failed task to the dead-letter queue in Redis."""
    import json
    r = get_redis()
    payload = json.dumps({"source_id": source_id, "error": error, "ts": time.time()})
    r.rpush(DLQ_KEY, payload)
    logger.critical(f"[DLQ] Permanent failure for source {source_id}: {error}")


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


def describe_error(exc: BaseException) -> str:
    """An exception as text that is never blank: some (httpx timeouts, connection resets) have no message."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


# Seconds before each retry of a failed source. They were 1, 2 and 4 minutes, which held a manual sync's
# last source for seven minutes; a source that is down for longer is better caught by the next sync.
RETRY_DELAYS = (15, 30, 60)


@celery_app.task
def crawl_all_sources(sync_id: str | None = None):
    """Crawl every active source. The API opens the sync for a manual one; a scheduled one opens its own."""
    from athena.database.operations import fetch_durations
    from athena.pipeline import sync_status
    r = get_redis()
    if sync_id is None:
        sources = get_active_sources()
        if not sources:
            logger.warning("No active sources found to sync!")
            return
        durations = fetch_durations([s.id for s in sources])
        sync_id = sync_status.start(r, [(str(s.id), s.name, durations.get(str(s.id))) for s in sources], "scheduled")
        if sync_id is None:
            logger.info("A sync is already running; the scheduled one is skipped.")
            return
    with logger.contextualize(sync_id=sync_id):
        ids = sync_status.source_ids(r, sync_id)
        logger.info(f"Syncing {len(ids)} sources...")
        for source_id in ids:
            crawl_source.delay(source_id, sync_id)


@celery_app.task(bind=True, max_retries=len(RETRY_DELAYS))
def crawl_source(self, source_id: str, sync_id: str | None = None):
    from contextlib import nullcontext
    from athena.pipeline import sync_status
    r = get_redis()
    with logger.contextualize(sync_id=sync_id) if sync_id else nullcontext():
        sync_status.source_started(r, sync_id, source_id)
        try:
            found, new = asyncio.run(_crawl_source_async(source_id, is_retry=self.request.retries > 0))
        except Exception as exc:
            error = describe_error(exc)
            if self.request.retries >= self.max_retries:
                _push_to_dlq(source_id, error)
                sync_status.source_finished(r, sync_id, source_id, "error", error=error)
                return  # Drop - already in DLQ, no more retries
            delay = RETRY_DELAYS[self.request.retries]
            logger.warning(f"Retrying in {delay} s: {error}")
            sync_status.source_retrying(r, sync_id, source_id, error, time.time() + delay)
            raise self.retry(exc=exc, countdown=delay)
        sync_status.source_finished(r, sync_id, source_id, "done" if found else "empty", new=new)


@celery_app.task(bind=True, max_retries=3, rate_limit="1/s")
def enrich_arxiv_paper(self, url: str, arxiv_id: str):
    try:
        asyncio.run(_enrich_paper_async(url, arxiv_id))
    except Exception as exc:
        logger.error(f"Enrichment task failed for {arxiv_id}: {describe_error(exc)}")
        raise self.retry(exc=exc, countdown=60)


async def _enrich_paper_async(url: str, arxiv_id: str):
    from athena.scrapers.semanticscholar import SemanticScholarEnricher
    from athena.database.operations import update_content_item_metrics

    ss_enricher = SemanticScholarEnricher()

    # Strip version suffix (e.g. 2403.00001v1 -> 2403.00001) as enrichment APIs prefer base IDs
    base_arxiv_id = re.sub(r'v\d+$', '', arxiv_id)

    logger.info(f"Enriching paper: {base_arxiv_id} (original: {arxiv_id})")
    # Papers With Code shut down in 2025 (its API redirects to Hugging Face), so only Semantic Scholar is asked;
    # repositories it found earlier stay in extra_data and still count towards engagement.
    ss_data = await ss_enricher.fetch_paper_metrics(base_arxiv_id)

    citation_count = ss_data.get("citation_count", 0) if ss_data else 0
    extra_data = {"semantic_scholar": ss_data}
    update_content_item_metrics(url, citation_count, extra_data)


def _get_scraper(source, source_id: str):
    """Factory: return the right scraper for this source type and URL."""
    url = source.url
    stype = source.type

    if stype == SourceType.API:
        if "arxiv" in url:
            return ArXivScraper(source_id=source_id)
    cat = source.category.value if hasattr(source.category, 'value') else str(source.category)
    if stype == SourceType.RSS:
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
            from athena.database.operations import known_urls
            return PlaywrightScraper(source_id=source_id, source_category=cat, known=known_urls)
    return None


async def _crawl_source_async(source_id: str, is_retry: bool = False) -> tuple[int, int]:
    """Crawl one source: (items it listed, new items saved). Listing nothing is logged as 'empty', not success."""
    from athena.database.db import SessionLocal
    from athena.core.models import Source, FetchLog, QuarantineItem
    from sqlalchemy import select

    with SessionLocal() as session:
        source = session.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if not source:
            logger.error(f"Source {source_id} not found.")
            return 0, 0

        if not source.is_active:
            logger.warning(f"Source {source.name} is inactive. Skipping.")
            return 0, 0

        logger.info(f"Crawling source: {source.name} ({source.url})")
        start_time = time.time()

        items = []
        new_urls = []
        found = 0
        error_msg = None
        status = "success"

        try:
            scraper = _get_scraper(source, source_id)
            if scraper is None:
                logger.warning(f"No scraper configured for {source.name}. Skipping.")
                status, error_msg = "empty", "No scraper handles this source's type and URL"
                return 0, 0

            # Parse per item, so one record failing validation is quarantined instead of failing the source
            if isinstance(scraper, ArXivScraper):
                from athena.database.operations import latest_published
                from athena.scrapers.arxiv import sync_args
                raw_items = await scraper.fetch(**sync_args(source.fetch_config, latest_published(source.id)))
            else:
                raw_items = await scraper.fetch(source.url)
            # Scrapers that skip pages already stored say how many they listed; the rest return all of them
            found = scraper.found if scraper.found is not None else len(raw_items)

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
            elif raw_items:
                logger.warning(f"None of the {len(raw_items)} items from {source.name} could be read; "
                               "they are in the quarantine.")
            elif found:
                logger.info(f"No new items from {source.name} ({found} listed, all already stored).")
            else:
                status, error_msg = "empty", f"Nothing found at {source.url}"
                logger.warning(f"{source.name} listed nothing at {source.url}; check the source's URL.")

            # Reset consecutive failures on success
            source.consecutive_failures = 0

        except Exception as e:
            error_msg = describe_error(e)
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

        return found, len(new_urls)


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
