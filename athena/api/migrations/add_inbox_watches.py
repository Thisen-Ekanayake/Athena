"""
Athena — inbox watches migration (ROADMAP N1)

Creates the tables for follows (watches), what they caught (watch hits) and each
user's inbox settings, and gives inbox events an owner column for per-user
entries (watch matches, digests). Map updates now reach a map's followers only,
so once per database every active user follows every built map; a marker in
app_settings keeps later runs from following maps again that people dropped.
Safe to run more than once; scripts/setup_project.py runs it.
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text

from athena.core.models import InboxSettings, Watch, WatchHit
from athena.database.db import engine

TABLES = [InboxSettings, Watch, WatchHit]
STATEMENTS = [
    "ALTER TABLE inbox_events ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;",
    "CREATE INDEX IF NOT EXISTS ix_inbox_events_user_id ON inbox_events (user_id);",
]
BACKFILL_MARKER = "INBOX_MAP_FOLLOWS_BACKFILLED"


def run_migration():
    """Create the new tables, add the owner column if it is missing, then the one-time map follows."""
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
    follow_built_maps()
    logger.info("Inbox watches migration complete.")


def follow_built_maps() -> int:
    """Once per database: every active user follows every built map, so nobody's inbox goes quiet."""
    from sqlalchemy import select

    from athena.core.config_store import get_setting, set_setting
    from athena.core.models import EvoTopic, User
    from athena.database import watches
    from athena.database.db import SessionLocal
    if get_setting(BACKFILL_MARKER):
        return 0
    added = 0
    with SessionLocal() as session:
        topics = session.execute(select(EvoTopic.id).where(EvoTopic.built_at.isnot(None))).scalars().all()
        for user_id in session.execute(select(User.id).where(User.is_active.is_(True))).scalars().all():
            for topic_id in topics:
                added += watches.follow_map(session, user_id, topic_id)
        session.commit()
    set_setting(BACKFILL_MARKER, datetime.now(timezone.utc).isoformat())
    logger.info(f"Followed built maps for existing users: {added} follows")
    return added


if __name__ == "__main__":
    run_migration()
