"""
Athena Layer 3 — Scoring Worker

Celery tasks for computing, persisting, and updating content scores.
Consumes items from the Redis scoring queue (emitted after Layer 2 embedding).
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import redis as redis_lib
from celery import shared_task
from loguru import logger
from sqlalchemy import select, update, text

from athena.database.db import SessionLocal
from athena.core.models import (
    ContentItem, ContentScore, ScoringConfig, MetricSnapshot, Source
)
from athena.pipeline.signals import (
    compute_citation_score,
    compute_engagement_score,
    compute_sentiment_score,
    compute_recency_score,
    compute_velocity_score,
    compute_authority_score,
    compute_composite_score,
    apply_trending_boost,
    check_trending_criteria,
    _extract_engagement_signals,
)

SCORING_QUEUE_KEY = "athena:scoring_queue"
BATCH_SIZE = 20


# ──────────────────────────────────────────────────────────
# Default scoring config weights per category
# ──────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "paper": {
        "citation": 0.30, "engagement": 0.15, "sentiment": 0.15,
        "recency": 0.20, "authority": 0.20, "half_life_days": 60,
    },
    "company_blog": {
        "citation": 0.10, "engagement": 0.25, "sentiment": 0.20,
        "recency": 0.30, "authority": 0.15, "half_life_days": 14,
    },
    "community_blog": {
        "citation": 0.10, "engagement": 0.30, "sentiment": 0.20,
        "recency": 0.25, "authority": 0.15, "half_life_days": 21,
    },
}

# Default authority scores for known source types
DEFAULT_AUTHORITY = {
    "arxiv": 0.85,
    "neurips": 1.0, "icml": 1.0, "iclr": 1.0,
    "deepmind": 0.90, "openai": 0.90, "anthropic": 0.90, "meta": 0.90,
    "towardsdatascience": 0.60, "medium": 0.60,
    "lesswrong": 0.75, "alignmentforum": 0.75,
    "substack": 0.55,
}


def _get_openai_client():
    """Lazy-load OpenAI client."""
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            return OpenAI(api_key=api_key)
    except ImportError:
        pass
    return None


def _get_weights(category: str, session) -> Dict[str, Any]:
    """Fetch active scoring config weights for the given category, or use defaults."""
    try:
        config = session.execute(
            select(ScoringConfig)
            .where(ScoringConfig.is_active .is_(True))
            .where(ScoringConfig.category == category)
            .order_by(ScoringConfig.version.desc())
        ).scalar_one_or_none()

        if config:
            return {
                "citation": config.weight_citation,
                "engagement": config.weight_engagement,
                "sentiment": config.weight_sentiment,
                "recency": config.weight_recency,
                "authority": config.weight_authority,
                "half_life_days": config.half_life_days,
                "version": config.version,
            }
    except Exception as e:
        logger.warning(f"Failed to load scoring config for {category}: {e}")

    cat_key = category if category in DEFAULT_WEIGHTS else "paper"
    default = DEFAULT_WEIGHTS[cat_key].copy()
    default["version"] = 1
    return default


def _get_prev_snapshot(item_id, session) -> tuple:
    """Get previous metric snapshot from ~7 days ago for velocity computation."""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    prev = session.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.item_id == item_id)
        .where(MetricSnapshot.snapshot_date <= seven_days_ago)
        .order_by(MetricSnapshot.snapshot_date.desc())
    ).scalar_one_or_none()

    if prev:
        return prev.citation_count, prev.engagement_raw
    return 0, 0.0


def score_item(item_id: str, session=None) -> Optional[float]:
    """
    Full scoring pipeline for a single item.
    Computes all 5 signals, composite score, trending status, and persists results.
    """
    close_session = False
    if session is None:
        session = SessionLocal()
        close_session = True

    try:
        item = session.execute(
            select(ContentItem).where(ContentItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            logger.warning(f"Item {item_id} not found for scoring.")
            return None

        # Fetch source for authority_score
        source = session.execute(
            select(Source).where(Source.id == item.source_id)
        ).scalar_one_or_none()

        category = item.category.value if hasattr(item.category, 'value') else str(item.category)
        weights = _get_weights(category, session)

        # Merge metadata from extra_data
        metadata = item.extra_data or {}

        # 1. Citation
        citation = compute_citation_score(item.citation_count or 0)

        # 2. Engagement
        source_url = source.url if source else ""
        engagement = compute_engagement_score(metadata, source_url)

        # 3. Sentiment (uses OpenAI — may return 0.5 if unavailable)
        openai_client = _get_openai_client()
        sentiment = compute_sentiment_score(metadata, openai_client)

        # 4. Recency
        half_life = weights.get("half_life_days", 30)
        recency = compute_recency_score(item.published_at, half_life)

        # 5. Velocity (from metric snapshots)
        prev_citations, prev_engagement = _get_prev_snapshot(item.id, session)
        velocity = compute_velocity_score(
            item.citation_count or 0, engagement,
            prev_citations, prev_engagement,
        )

        # Combined recency signal = 60% recency + 40% velocity
        recency_combined = 0.6 * recency + 0.4 * velocity

        # 6. Authority
        authority = compute_authority_score(source.authority_score if source else None)

        # 7. Composite
        composite = compute_composite_score(
            citation, engagement, sentiment, recency_combined, authority, weights
        )

        # 8. Trending check
        engagement_signals = _extract_engagement_signals(metadata, source_url)
        is_trending = check_trending_criteria(
            velocity, item.published_at, len(engagement_signals)
        )

        # 9. Apply trending boost
        final_score = apply_trending_boost(composite, is_trending)

        # 10. Persist ContentScore
        version = weights.get("version", 1)
        now = datetime.now(timezone.utc)

        score_record = ContentScore(
            item_id=item.id,
            citation_score=citation,
            engagement_score=engagement,
            sentiment_score=sentiment,
            recency_score=recency_combined,
            authority_score=authority,
            composite_score=final_score,
            score_version=version,
            computed_at=now,
        )
        session.add(score_record)

        # 11. Update ContentItem
        session.execute(
            update(ContentItem).where(ContentItem.id == item.id).values(
                score=final_score,
                score_version=version,
                scored_at=now,
                is_trending=is_trending,
            )
        )
        session.commit()

        # Enqueue for summarisation
        enqueue_summary_tier(str(item.id), final_score, is_trending)

        logger.info(
            f"Scored item {item_id}: composite={final_score:.3f} "
            f"(C={citation:.2f} E={engagement:.2f} S={sentiment:.2f} "
            f"R={recency_combined:.2f} A={authority:.2f}) trending={is_trending}"
        )
        return final_score

    except Exception as e:
        session.rollback()
        logger.error(f"Scoring failed for item {item_id}: {e}")
        return None
    finally:
        if close_session:
            session.close()


def update_category_ranks():
    """
    Refresh category_rank for all active items using SQL RANK() window function.
    """
    rank_sql = text("""
        UPDATE content_items ci
        SET category_rank = ranked.rank
        FROM (
            SELECT
                id,
                RANK() OVER (
                    PARTITION BY category
                    ORDER BY score DESC NULLS LAST
                ) AS rank
            FROM content_items
            WHERE score IS NOT NULL
        ) ranked
        WHERE ci.id = ranked.id
    """)

    with SessionLocal() as session:
        session.execute(rank_sql)
        session.commit()
        logger.info("Category ranks updated.")


# ──────────────────────────────────────────────────────────
# Celery Tasks
# ──────────────────────────────────────────────────────────

def _get_celery_app():
    """Lazy import to avoid circular dependency."""
    from athena.pipeline.tasks import celery_app
    return celery_app


@shared_task
def process_scoring_queue():
    """Pull items from the scoring queue and score them."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis_lib.from_url(redis_url)

    item_ids = []
    for _ in range(BATCH_SIZE):
        item_id = r.lpop(SCORING_QUEUE_KEY)
        if not item_id:
            break
        item_ids.append(item_id.decode("utf-8"))

    if not item_ids:
        return

    logger.info(f"Processing scoring queue batch of {len(item_ids)} items.")

    with SessionLocal() as session:
        for item_id in item_ids:
            score_item(item_id, session)

    update_category_ranks()


@shared_task
def score_all_items():
    """Batch re-score all items (triggered by config change or enrichment refresh)."""
    logger.info("Starting full corpus re-score...")

    with SessionLocal() as session:
        items = session.execute(
            select(ContentItem.id)
        ).scalars().all()

    for item_id in items:
        score_item(str(item_id))

    update_category_ranks()
    logger.info(f"Full re-score complete. {len(items)} items processed.")


@shared_task
def refresh_recency_scores():
    """Periodic task: recency scores drift as time passes — recompute for all scored items."""
    logger.info("Refreshing recency scores...")

    with SessionLocal() as session:
        items = session.execute(
            select(ContentItem.id).where(ContentItem.scored_at.isnot(None))
        ).scalars().all()

    for item_id in items:
        score_item(str(item_id))

    update_category_ranks()
    logger.info(f"Recency refresh complete. {len(items)} items re-scored.")


@shared_task
def take_metric_snapshot():
    """Daily snapshot: capture current citation_count + engagement for velocity computation."""
    logger.info("Taking daily metric snapshot...")
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        items = session.execute(
            select(ContentItem)
        ).scalars().all()

        for item in items:
            metadata = item.extra_data or {}
            source = session.execute(
                select(Source).where(Source.id == item.source_id)
            ).scalar_one_or_none()
            source_url = source.url if source else ""
            eng_signals = _extract_engagement_signals(metadata, source_url)
            eng_raw = sum(eng_signals) / len(eng_signals) if eng_signals else 0.0

            snapshot = MetricSnapshot(
                item_id=item.id,
                citation_count=item.citation_count or 0,
                engagement_raw=eng_raw,
                snapshot_date=now,
            )
            session.add(snapshot)

        session.commit()
        logger.info(f"Metric snapshot complete. {len(items)} snapshots saved.")


@shared_task
def score_new_item(item_id: str):
    """Score a single newly embedded item and update ranks."""
    score_item(item_id)
    update_category_ranks()


def enqueue_summary_tier(item_id: str, score: float, is_trending: bool):
    """Emits the item to the correct Celery queue based on Layer 3 score."""
    from athena.pipeline.summarisation_tasks import summarise_item_worker

    if is_trending or score >= 0.75:
        # Tier 1 - Urgent
        summarise_item_worker.apply_async(args=[item_id], queue='summary_urgent')
        logger.info(f"Item {item_id} enqueued to summary_urgent")
    elif score >= 0.40:
        # Tier 2 - handled by hourly batch, just set to pending
        with SessionLocal() as session:
            from athena.core.models import ContentItem, SummaryStatus
            session.execute(
                update(ContentItem).where(ContentItem.id == item_id).values(
                    summary_status=SummaryStatus.PENDING
                )
            )
            session.commit()
        logger.info(f"Item {item_id} marked as pending for Tier 2 batch")
    else:
        # Tier 3 - Lazy
        with SessionLocal() as session:
            from athena.core.models import ContentItem, SummaryStatus
            session.execute(
                update(ContentItem).where(ContentItem.id == item_id).values(
                    summary_status=SummaryStatus.LAZY
                )
            )
            session.commit()
        logger.info(f"Item {item_id} marked as lazy summarisation")


def populate_default_scoring_config():
    """Populate the scoring_config table with default weight profiles."""
    with SessionLocal() as session:
        existing = session.execute(select(ScoringConfig)).scalars().all()
        if existing:
            logger.info("Scoring config already populated, skipping.")
            return

        version = 1
        for category, weights in DEFAULT_WEIGHTS.items():
            config = ScoringConfig(
                version=version,
                category=category,
                weight_citation=weights["citation"],
                weight_engagement=weights["engagement"],
                weight_sentiment=weights["sentiment"],
                weight_recency=weights["recency"],
                weight_authority=weights["authority"],
                half_life_days=weights["half_life_days"],
                is_active=True,
                notes="Default config",
            )
            session.add(config)
            version += 1
        session.commit()
        logger.info("Default scoring config populated.")


def populate_default_authority_scores():
    """Assign authority_score to all existing sources based on URL keywords."""
    with SessionLocal() as session:
        sources = session.execute(select(Source)).scalars().all()
        for source in sources:
            url_lower = source.url.lower()
            for keyword, score in DEFAULT_AUTHORITY.items():
                if keyword in url_lower:
                    source.authority_score = score
                    break
        session.commit()
        logger.info(f"Authority scores assigned to {len(sources)} sources.")
