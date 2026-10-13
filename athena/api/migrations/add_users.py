"""
Athena — accounts migration

Creates the users and user_sessions tables and adds the owner columns that
came with accounts: saved_lists.user_id (list names become unique per user),
qa_usage_log.user_id and evo_topics.created_by. Lists from before accounts
keep a null owner until the first admin account is created, which takes them
over. Safe to run more than once; scripts/setup_project.py runs it.
"""
from loguru import logger
from sqlalchemy import text

from athena.core.models import User, UserSession
from athena.database.db import engine

STATEMENTS = [
    "ALTER TABLE saved_lists ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;",
    "CREATE INDEX IF NOT EXISTS ix_saved_lists_user_id ON saved_lists (user_id);",
    "ALTER TABLE saved_lists DROP CONSTRAINT IF EXISTS saved_lists_name_key;",
    """DO $$ BEGIN
         ALTER TABLE saved_lists ADD CONSTRAINT uq_saved_list_user_name UNIQUE (user_id, name);
       EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
       END $$;""",
    "ALTER TABLE qa_usage_log ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;",
    "ALTER TABLE evo_topics ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;",
]


def run_migration():
    """Create the account tables, then add the owner columns if they are missing."""
    User.__table__.create(bind=engine, checkfirst=True)
    UserSession.__table__.create(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        for stmt in STATEMENTS:
            try:
                conn.execute(text(stmt))
                logger.info(f"Applied: {' '.join(stmt.split())[:70]}...")
            except Exception as e:
                conn.rollback()
                logger.warning(f"Statement skipped: {e}")
        conn.commit()
    logger.info("Accounts migration complete.")


if __name__ == "__main__":
    run_migration()
