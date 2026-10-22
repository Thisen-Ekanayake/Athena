"""
The beat schedule: every periodic task, and the hourly check of the model budget.

``celery -A athena.pipeline.tasks worker -B`` runs it; athena.pipeline.tasks imports this module.
"""
import athena.evolution.tasks
import athena.pipeline.clustering
import athena.pipeline.crawl
import athena.pipeline.embedding_worker
import athena.pipeline.momentum
import athena.pipeline.scoring
import athena.pipeline.summarisation_tasks
import athena.pipeline.watches
from athena.pipeline.celery_app import celery_app

# A once-a-minute run still waiting in a busy worker's queue after this many seconds is dropped: the next one is
# on its way. Ones that waited out a sync's backlog all ran at once, more of them than the database pool has
# connections, and the runs that got none lost the items they had taken from their queue.
MINUTE_RUN_EXPIRES = 55


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Poll all feeds every 6 hours (21600 seconds)
    sender.add_periodic_task(21600.0, athena.pipeline.crawl.crawl_all_sources.s(), name='crawl every 6 hours')
    # Run embedding worker every 1 minute
    sender.add_periodic_task(
        60.0,
        athena.pipeline.embedding_worker.process_embedding_queue.s(),
        name='process embeddings every 1 minute', expires=MINUTE_RUN_EXPIRES)
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
                             name='process scoring queue every 1 minute', expires=MINUTE_RUN_EXPIRES)
    # Semantic Scholar counts for the new arXiv papers, in batches, every 1 minute
    sender.add_periodic_task(60.0, athena.pipeline.crawl.process_enrich_queue.s(),
                             name='enrich new papers every 1 minute', expires=MINUTE_RUN_EXPIRES)
    # Refresh recency scores every 6 hours
    sender.add_periodic_task(21600.0,
                             athena.pipeline.scoring.refresh_recency_scores.s(),
                             name='refresh recency scores every 6 hours')
    # Citation counts, metric snapshots and 7/30-day gains: checked hourly, done once per UTC day (a 24 h interval
    # restarts its clock with beat and never fired on machines that restart often)
    sender.add_periodic_task(3600.0, athena.pipeline.momentum.daily_momentum.s(), name='daily citation momentum')
    # Hourly summaries: every item without one, highest score first
    sender.add_periodic_task(3600.0, athena.pipeline.summarisation_tasks.enqueue_tier2_summaries.s(),
                             name='hourly tier 2 summaries')
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


@celery_app.task(name="athena.pipeline.tasks.check_model_budget")
def check_model_budget():
    """Tell the admins, once a month each, when model spend passes 80% and then 100% of the monthly budget."""
    from athena.core import usage
    from athena.database.db import SessionLocal
    usage.flush()  # this worker's own background calls count too
    with SessionLocal() as session:
        threshold = usage.budget_alerts(session)
        session.commit()
    return threshold
