"""
The Celery entry point (``celery -A athena.pipeline.tasks worker``): importing it registers every task module and
the beat schedule (athena.pipeline.beat). The crawl is in athena.pipeline.crawl, the scraper choice in
athena.scrapers.choose.
"""
from athena.core.logging import setup_redis_logging
from athena.pipeline.celery_app import celery_app  # noqa: F401  (the app ``celery -A`` finds)
import athena.pipeline.embedding_worker  # noqa: F401
import athena.pipeline.clustering  # noqa: F401
import athena.pipeline.scoring  # noqa: F401
import athena.pipeline.summarisation_tasks  # noqa: F401  (registers the summary tasks with every worker)
import athena.evolution.tasks  # noqa: F401  (registers the evolution queue's tasks)
import athena.pipeline.watches  # noqa: F401  (registers the watch checks and digests)
import athena.pipeline.momentum  # noqa: F401  (registers the daily citation momentum)
import athena.projects.tasks  # noqa: F401  (registers project indexing)
import athena.pipeline.beat  # noqa: F401  (the periodic tasks)
from athena.pipeline.crawl import (  # noqa: F401  (imported from here by scripts and user_sources)
    STAGING_DIR, _crawl_source_async, _preprocess_text, crawl_all_sources, crawl_source, describe_error,
    enrich_arxiv_paper, stage_content_item,
)
from athena.pipeline.summarisation_tasks import enqueue_tier2_summaries  # noqa: F401

# Initialize Redis logging sink for live sync feedback
setup_redis_logging()
