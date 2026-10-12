"""
Athena — EvoTopic origin migration

Adds the columns search-built research-evolution topics need: where a topic
came from (``curated`` or ``search``), the search it came from, and the last
build's summary. Existing topics are curated.
"""
from sqlalchemy import text
from athena.database.db import engine
from loguru import logger


STATEMENTS = [
    "ALTER TABLE evo_topics ADD COLUMN IF NOT EXISTS origin VARCHAR NOT NULL DEFAULT 'curated';",
    "ALTER TABLE evo_topics ADD COLUMN IF NOT EXISTS query VARCHAR;",
    "ALTER TABLE evo_topics ADD COLUMN IF NOT EXISTS build_stats JSONB;",
]


def run_migration():
    """Add the origin, query and build_stats columns if they are missing."""
    with engine.connect() as conn:
        for stmt in STATEMENTS:
            try:
                conn.execute(text(stmt))
                logger.info(f"Applied: {stmt[:60]}...")
            except Exception as e:
                logger.warning(f"Statement skipped: {e}")
        conn.commit()
        logger.info("EvoTopic origin migration complete.")


if __name__ == "__main__":
    run_migration()
