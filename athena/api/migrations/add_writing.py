"""
Athena — search and writing migration (ROADMAP S1–S3)

Creates the literature reviews table (lit_reviews). Adds full-text search to the feed: a generated
``search_vector`` on content_items (title weighted A, summary B, abstract C, English parser) and a GIN index on
it, for keyword plus meaning search (athena.search.hybrid). The column fills itself for existing rows when it is
added. Postgres only: on another database those statements are skipped and search keeps its substring fallback.
Safe to run more than once; scripts/setup_project.py runs it.
"""
from loguru import logger
from sqlalchemy import text

from athena.core.models import LitReview
from athena.database.db import engine

TABLES = [LitReview]
SEARCH_VECTOR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(abstract, '')), 'C')"
)
POSTGRES_STATEMENTS = [
    f"ALTER TABLE content_items ADD COLUMN IF NOT EXISTS search_vector tsvector "
    f"GENERATED ALWAYS AS ({SEARCH_VECTOR}) STORED;",
    "CREATE INDEX IF NOT EXISTS ix_content_items_search ON content_items USING GIN (search_vector);",
]


def run_migration():
    """Create the new tables, then add what Postgres needs for full-text search."""
    for model in TABLES:
        model.__table__.create(bind=engine, checkfirst=True)
    if engine.dialect.name != "postgresql":
        logger.info("Writing migration: not Postgres, full-text search skipped.")
        return
    with engine.connect() as conn:
        for stmt in POSTGRES_STATEMENTS:
            try:
                conn.execute(text(stmt))
                logger.info(f"Applied: {' '.join(stmt.split())[:70]}...")
            except Exception as e:
                conn.rollback()
                logger.warning(f"Statement skipped: {e}")
        conn.commit()
    logger.info("Writing migration complete.")


if __name__ == "__main__":
    run_migration()
