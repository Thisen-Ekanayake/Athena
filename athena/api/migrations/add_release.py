"""
Athena — release migration (ROADMAP R1–R3)

Creates the usage log (every model call, for the usage page and the monthly budget) and the
share links for maps, and adds users.onboarded_at for the setup guide. Accounts that existed
before the guide are marked as done once per database, so only new accounts see it; a marker
in app_settings keeps later runs from marking new accounts too. Safe to run more than once;
scripts/setup_project.py runs it.
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text

from athena.core.models import MapShare, UsageEvent
from athena.database.db import engine

TABLES = [UsageEvent, MapShare]
STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMP WITH TIME ZONE;",
]
BACKFILL_MARKER = "ONBOARDING_BACKFILLED"


def run_migration():
    """Create the new tables, add the onboarding column if it is missing, then mark existing accounts once."""
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
    mark_existing_accounts()
    logger.info("Release migration complete.")


def mark_existing_accounts() -> int:
    """Once per database: accounts made before the setup guide count as having seen it."""
    from athena.core.config_store import get_setting, set_setting
    if get_setting(BACKFILL_MARKER):
        return 0
    with engine.begin() as conn:
        marked = conn.execute(text("UPDATE users SET onboarded_at = created_at WHERE onboarded_at IS NULL")).rowcount
    set_setting(BACKFILL_MARKER, datetime.now(timezone.utc).isoformat())
    logger.info(f"Existing accounts marked as onboarded: {marked}")
    return marked


if __name__ == "__main__":
    run_migration()
