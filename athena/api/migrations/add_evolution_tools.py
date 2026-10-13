"""
Athena — research evolution tools migration (ROADMAP E1-E9)

Creates the tables the reading path, idea checks, map questions, snapshots,
cross-map links and the inbox need, and adds the columns they read: OpenAlex authorships
(people view), the name citing papers use (a milestone-score feature) and when
a gap statement was searched against other maps. Each built topic without a
snapshot gets a baseline one, so its first refresh has something to compare
with. Safe to run more than once; scripts/setup_project.py runs it.
"""
from loguru import logger
from sqlalchemy import text

from athena.core.models import (
    EvoCrossLink, EvoIdeaCheck, EvoMapQuestion, EvoPaperNote, EvoReadingProgress, EvoSnapshot, InboxEvent, InboxState,
)
from athena.database.db import engine

TABLES = [EvoCrossLink, EvoPaperNote, EvoReadingProgress, EvoIdeaCheck, EvoMapQuestion, EvoSnapshot, InboxEvent,
          InboxState]
STATEMENTS = [
    "ALTER TABLE evo_papers ADD COLUMN IF NOT EXISTS authorships JSONB DEFAULT '[]'::jsonb;",
    "ALTER TABLE evo_papers ADD COLUMN IF NOT EXISTS cited_name JSONB;",
    "ALTER TABLE evo_gap_statements ADD COLUMN IF NOT EXISTS cross_checked_at TIMESTAMPTZ;",
]


def run_migration():
    """Create the new tables, then add the new columns if they are missing."""
    for model in TABLES:
        model.__table__.create(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        for stmt in STATEMENTS:
            try:
                conn.execute(text(stmt))
                logger.info(f"Applied: {' '.join(stmt.split())[:70]}...")
            except Exception as e:
                conn.rollback()
                logger.warning(f"Statement skipped: {e}")
        conn.commit()
    baseline_snapshots()
    logger.info("Evolution tools migration complete.")


def baseline_snapshots() -> int:
    from sqlalchemy import select

    from athena.core.models import EvoTopic
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    taken = 0
    with SessionLocal() as session:
        have = set(session.execute(select(EvoSnapshot.topic_id).distinct()).scalars())
        for topic in session.execute(select(EvoTopic).where(EvoTopic.built_at.isnot(None))).scalars().all():
            if topic.id not in have:
                db.take_snapshot(session, topic, "baseline")
                taken += 1
    logger.info(f"Took {taken} baseline snapshots")
    return taken


if __name__ == "__main__":
    run_migration()
