"""
Athena — reading and personalisation migration (ROADMAP P1–P3)

Creates read marks for feed items and users' notes and highlights (on feed items and map papers). Adds what
citation momentum needs: a source on metric snapshots (daily, or rebuilt from citing papers' dates), an index to
read one item's history, and each item's citation gains over 7 and 30 days. Safe to run more than once;
scripts/setup_project.py runs it.
"""
from loguru import logger
from sqlalchemy import text

from athena.core.models import ItemRead, UserHighlight, UserNote
from athena.database.db import engine

TABLES = [ItemRead, UserNote, UserHighlight]
STATEMENTS = [
    "ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'daily';",
    "CREATE INDEX IF NOT EXISTS ix_metric_snapshots_item_date ON metric_snapshots (item_id, snapshot_date);",
    "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS citation_gain_7d INTEGER;",
    "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS citation_gain_30d INTEGER;",
]


def run_migration():
    """Create the new tables, then add the columns and indexes that are missing."""
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
    logger.info("Reading migration complete.")


if __name__ == "__main__":
    run_migration()
