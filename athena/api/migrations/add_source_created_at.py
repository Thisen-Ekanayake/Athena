"""
Athena — Source.created_at migration

Adds a `created_at` timestamp to the `sources` table so the UI can sort
sources by date created. Existing rows default to the migration time
(true creation order cannot be recovered from random UUIDs).
"""
from sqlalchemy import text
from athena.database.db import engine
from loguru import logger


STATEMENTS = [
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS created_at "
    "TIMESTAMPTZ NOT NULL DEFAULT now();",
]


def run_migration():
    """Add the created_at column if it is missing."""
    with engine.connect() as conn:
        for stmt in STATEMENTS:
            try:
                conn.execute(text(stmt))
                logger.info(f"Applied: {stmt[:60]}...")
            except Exception as e:
                logger.warning(f"Statement skipped: {e}")
        conn.commit()
        logger.info("Source.created_at migration complete.")


if __name__ == "__main__":
    run_migration()
