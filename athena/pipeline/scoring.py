"""
Athena Layer 3 — Scoring Worker

Celery tasks for computing, persisting, and updating content scores.
Consumes items from the Redis scoring queue (emitted after Layer 2 embedding).
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from uuid import UUID

import numpy as np
from celery import shared_task
from loguru import logger
from sqlalchemy import select, update, text

from athena.database.db import SessionLocal
from athena.core.models import (
    ContentItem, ContentScore, ScoringConfig, MetricSnapshot, Source
)
from athena.core.redis_client import get_redis
from athena.pipeline.signals import (
    compute_citation_score,
    compute_engagement_score,
    compute_recency_score,
    compute_velocity_score,
    compute_authority_score,
    compute_composite_score,
    apply_trending_boost,
    check_trending_criteria,
    _extract_engagement_signals,
)
from athena.pipeline.mlflow_utils import mlflow_run, ml_log

SCORING_QUEUE_KEY = "athena:scoring_queue"
BATCH_SIZE = 200  # scoring is a few queries an item; 20 a minute fell behind a sync's arXiv papers
# Stream rows from the DB in bounded chunks so full-corpus tasks don't
# materialise every ContentItem in RAM at once.
CHUNK_SIZE = 500


# ──────────────────────────────────────────────────────────
# Default scoring config weights per category
# ──────────────────────────────────────────────────────────

# The four signal weights sum to 1. A category gets no weight on a signal it has no data for: blogs are never
# cited, and only community sites (LessWrong) report engagement, so those signals would be the same 0.5 for every
# item and shift whole categories against each other in the mixed feed. "preference" is not part of the score: it
# is the share a user's interests get in their "For you" order (athena.pipeline.interests).
BASE_SIGNALS = ("citation", "engagement", "recency", "authority")
DEFAULT_PREFERENCE = 0.30
DEFAULT_WEIGHTS = {
    "paper": {
        "citation": 0.40, "engagement": 0.0,
        "recency": 0.35, "authority": 0.25, "half_life_days": 60, "preference": DEFAULT_PREFERENCE,
    },
    "company_blog": {
        "citation": 0.0, "engagement": 0.0,
        "recency": 0.60, "authority": 0.40, "half_life_days": 14, "preference": DEFAULT_PREFERENCE,
    },
    "community_blog": {
        "citation": 0.0, "engagement": 0.40,
        "recency": 0.35, "authority": 0.25, "half_life_days": 21, "preference": DEFAULT_PREFERENCE,
    },
}

# Default authority per source, by what its URL contains. A key with a dot and no slash is a domain and matches
# that host or its subdomains (so "x.ai" is not any host ending in "x.ai"); any other key matches anywhere in the
# host and path. The first match wins. Sources none of them match keep the neutral 0.5.
DEFAULT_SOURCE_AUTHORITY = 0.5
DEFAULT_AUTHORITY = {
    "arxiv": 0.85,
    "neurips": 1.0, "icml": 1.0, "iclr": 1.0,
    "deepmind": 0.90, "openai": 0.90, "anthropic": 0.90, "ai.meta.com": 0.90,
    "microsoft.com/en-us/research": 0.85,
    "huggingface.co": 0.80,
    "lesswrong": 0.75, "alignmentforum": 0.75, "thegradient.pub": 0.75,
    "nvidia.com": 0.70, "x.ai": 0.70,
    "towardsdatascience": 0.60, "medium": 0.60,
    "substack": 0.55,
}


def default_authority(url: str) -> Optional[float]:
    """The default authority for a source URL (DEFAULT_AUTHORITY), or None when no key matches."""
    from urllib.parse import urlparse
    parsed = urlparse(url.lower() if "//" in url else f"//{url.lower()}")
    host = parsed.netloc.split("@")[-1].split(":")[0].removeprefix("www.")
    for key, score in DEFAULT_AUTHORITY.items():
        if "." in key and "/" not in key:
            if host == key or host.endswith(f".{key}"):
                return score
        elif key in host + parsed.path:
            return score
    return None


def _get_weights(category: str, session) -> Dict[str, Any]:
    """Fetch active scoring config weights for the given category, or use defaults."""
    try:
        config = session.execute(
            select(ScoringConfig)
            .where(ScoringConfig.is_active .is_(True))
            .where(ScoringConfig.category == category)
            .order_by(ScoringConfig.version.desc())
        ).scalars().first()

        if config:
            return {
                "citation": config.weight_citation,
                "engagement": config.weight_engagement,
                "recency": config.weight_recency,
                "authority": config.weight_authority,
                "half_life_days": config.half_life_days,
                "preference": DEFAULT_PREFERENCE if config.weight_preference is None else config.weight_preference,
                "version": config.version,
                "saved": True,
            }
    except Exception as e:
        logger.warning(f"Failed to load scoring config for {category}: {e}")

    cat_key = category if category in DEFAULT_WEIGHTS else "paper"
    default = DEFAULT_WEIGHTS[cat_key].copy()
    default["version"] = 1
    return default


def engagement_raw(signals: list) -> float:
    """The mean of an item's normalised engagement signals, or 0 without any: what metric snapshots store."""
    return sum(signals) / len(signals) if signals else 0.0


def _get_prev_snapshot(item_id, session) -> tuple | None:
    """(citations, raw engagement) from the latest metric snapshot at least 7 days old, or None without one."""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    prev = session.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.item_id == item_id)
        .where(MetricSnapshot.snapshot_date <= seven_days_ago)
        .order_by(MetricSnapshot.snapshot_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if prev:
        return prev.citation_count, prev.engagement_raw
    return None


def _week_ago_metrics(item, session, eng_now: float) -> tuple:
    """What an item had a week ago. Without a snapshot from then, an item younger than a week had nothing, and
    for an older one there is nothing to compare with, so it counts as unchanged (not as gaining everything)."""
    prev = _get_prev_snapshot(item.id, session)
    if prev is not None:
        return prev
    published = item.published_at
    if published is not None and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    if published is not None and datetime.now(timezone.utc) - published < timedelta(days=7):
        return 0, 0.0
    return item.citation_count or 0, eng_now


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
        engagement_signals = _extract_engagement_signals(metadata, source_url)

        # 3. Recency
        half_life = weights.get("half_life_days", 30)
        recency = compute_recency_score(item.published_at, half_life)

        # 4. Velocity (from metric snapshots). Compared like with like: the raw engagement mean that snapshots
        # store, so an item without engagement data has none to gain (the 0.5 neutral score is not a reading).
        eng_now = engagement_raw(engagement_signals)
        prev_citations, prev_engagement = _week_ago_metrics(item, session, eng_now)
        velocity = compute_velocity_score(
            item.citation_count or 0, eng_now,
            prev_citations, prev_engagement,
        )

        # Combined recency signal = 60% recency + 40% velocity
        recency_combined = 0.6 * recency + 0.4 * velocity

        # 5. Authority
        authority = compute_authority_score(source.authority_score if source else None)

        # 6. Composite
        composite = compute_composite_score(citation, engagement, recency_combined, authority, weights)

        # 7. Trending check
        is_trending = check_trending_criteria(
            velocity, item.published_at, len(engagement_signals)
        )

        # 8. Apply trending boost
        final_score = apply_trending_boost(composite, is_trending)

        # 8.5 Log significant changes (> 0.1)
        old_score = item.score or 0.0
        delta = final_score - old_score
        # Only log if it's not the initial 0.0 -> score jump, meaning scored_at is not None
        if abs(delta) > 0.1 and item.scored_at is not None:
            from athena.core.models import ScoreAuditLog
            audit_log = ScoreAuditLog(
                item_id=item.id,
                old_score=old_score,
                new_score=final_score,
                delta=delta,
                reason="Significant score change during re-score"
            )
            session.add(audit_log)

        # 9. Persist ContentScore
        version = weights.get("version", 1)
        now = datetime.now(timezone.utc)

        score_record = ContentScore(
            item_id=item.id,
            citation_score=citation,
            engagement_score=engagement,
            recency_score=recency_combined,
            authority_score=authority,
            composite_score=final_score,
            score_version=version,
            computed_at=now,
        )
        session.add(score_record)

        # 10. Update ContentItem
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
            f"(C={citation:.2f} E={engagement:.2f} "
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
    from athena.pipeline.celery_app import celery_app
    return celery_app


@shared_task
def process_scoring_queue():
    """Pull items from the scoring queue and score them."""
    r = get_redis()

    item_ids = []
    for _ in range(BATCH_SIZE):
        item_id = r.lpop(SCORING_QUEUE_KEY)
        if not item_id:
            break
        item_ids.append(item_id.decode("utf-8"))

    if not item_ids:
        return

    logger.info(f"Processing scoring queue batch of {len(item_ids)} items.")

    import mlflow
    with mlflow_run("athena-scoring", "process_scoring_queue"):
        scores = []
        with SessionLocal() as session:
            for item_id in item_ids:
                s = score_item(item_id, session)
                if s is not None:
                    scores.append(s)

        update_category_ranks()

        ml_log(mlflow.log_metrics, {
            "batch_size": len(item_ids),
            "scored_count": len(scores),
            **({"mean_score": float(np.mean(scores)),
                "max_score": float(np.max(scores)),
                "trending_count": sum(1 for s in scores if s >= 0.75)} if scores else {}),
        })


def _iter_item_ids(stmt) -> Any:
    """Yield ContentItem UUIDs from ``stmt`` in ``CHUNK_SIZE`` rows at a time.

    Uses ``yield_per`` so the SQLAlchemy/psycopg2 driver streams rows in a
    server-side cursor instead of loading the whole result set into memory.
    """
    with SessionLocal() as session:
        result = session.execute(stmt.execution_options(yield_per=CHUNK_SIZE))
        for row in result.scalars():
            yield row


@shared_task
def score_all_items():
    """Batch re-score all items (triggered by config change or enrichment refresh)."""
    logger.info("Starting full corpus re-score...")

    import mlflow
    with mlflow_run("athena-scoring", "score_all_items"):
        scores = []
        total = 0
        for item_id in _iter_item_ids(select(ContentItem.id)):
            total += 1
            s = score_item(str(item_id))
            if s is not None:
                scores.append(s)

        update_category_ranks()

        ml_log(mlflow.log_metrics, {
            "total_items": total,
            "scored_count": len(scores),
            **({"mean_score": float(np.mean(scores)),
                "median_score": float(np.median(scores)),
                "p90_score": float(np.percentile(scores, 90)),
                "trending_count": sum(1 for s in scores if s >= 0.75)} if scores else {}),
        })
        logger.info(f"Full re-score complete. {total} items processed.")


@shared_task
def refresh_recency_scores():
    """Periodic task: recency scores drift as time passes — recompute for all scored items."""
    logger.info("Refreshing recency scores...")

    stmt = select(ContentItem.id).where(ContentItem.scored_at.isnot(None))

    import mlflow
    with mlflow_run("athena-scoring", "refresh_recency_scores"):
        scores = []
        total = 0
        for item_id in _iter_item_ids(stmt):
            total += 1
            s = score_item(str(item_id))
            if s is not None:
                scores.append(s)

        update_category_ranks()

        ml_log(mlflow.log_metrics, {
            "total_items": total,
            "scored_count": len(scores),
            **({"mean_score": float(np.mean(scores)),
                "median_score": float(np.median(scores))} if scores else {}),
        })
        logger.info(f"Recency refresh complete. {total} items re-scored.")


@shared_task
def take_metric_snapshot():
    """Kept for messages queued before athena.pipeline.momentum took over: runs the day's momentum work."""
    from athena.pipeline.momentum import daily_momentum
    return daily_momentum()


@shared_task
def score_new_item(item_id: str):
    """Score a single newly embedded item and update ranks."""
    score_item(item_id)
    update_category_ranks()


def enqueue_summary_tier(item_id: str, score: float, is_trending: bool):
    """Emits the item to the correct Celery queue based on Layer 3 score.

    An item whose summary is already complete is left alone: rescoring (every six hours for recency) must not
    send finished summaries back to the queue.
    """
    from athena.pipeline.summarisation_tasks import summarise_item_worker
    from athena.core.models import SummaryStatus

    item_uuid = UUID(str(item_id))
    with SessionLocal() as session:
        status = session.execute(select(ContentItem.summary_status).where(ContentItem.id == item_uuid)).scalar()
        if status == SummaryStatus.COMPLETE:
            return
        if is_trending or score >= 0.75:
            tier, new_status = "summary_urgent", None
        elif score >= 0.40:
            tier, new_status = "pending (Tier 2 batch)", SummaryStatus.PENDING
        else:
            tier, new_status = "lazy", SummaryStatus.LAZY
        if new_status is not None:
            session.execute(update(ContentItem).where(ContentItem.id == item_uuid).values(summary_status=new_status))
            session.commit()

    if new_status is None:
        # Tier 1 - Urgent
        summarise_item_worker.apply_async(args=[item_id], queue='summary_urgent')
    logger.info(f"Item {item_id} enqueued to {tier}")


def populate_default_authority_scores(source_id=None) -> int:
    """Give sources their default authority (default_authority), all of them or the one with this id.

    Only a source still at the neutral 0.5 (or none) gets one, so a value set by hand stays. Returns how many changed.
    """
    with SessionLocal() as session:
        query = select(Source)
        if source_id is not None:
            query = query.where(Source.id == UUID(str(source_id)))
        changed = 0
        for source in session.execute(query).scalars().all():
            if source.authority_score not in (None, DEFAULT_SOURCE_AUTHORITY):
                continue
            score = default_authority(source.url)
            if score is not None and score != source.authority_score:
                source.authority_score = score
                changed += 1
        session.commit()
    if changed:
        logger.info(f"Default authority given to {changed} source(s).")
    return changed
