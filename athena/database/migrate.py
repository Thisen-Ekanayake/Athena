"""
Database migrations with Alembic (revisions in alembic/versions/ at the repo root).

upgrade() brings the database to the newest revision; init_db() runs it when the API starts, and so does
scripts/setup_project.py. A database made before Alembic (tables, but no alembic_version) first gets what the old
setup ran, once: create_all, the athena/api/migrations/add_*.py scripts and one index create_all never added to an
existing table. It then matches the baseline revision and is stamped with it.
"""
import importlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import inspect, text

from athena.database.db import engine

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0001"
LOCK_KEY = 4_173_601  # Postgres advisory lock: one process migrates at a time

# What the old setup ran, in its order, plus the two scripts that were only run by hand. add_indexes.py is not
# here: its indexes never reached a database, and the baseline doesn't have them.
LEGACY_SCRIPTS = ["add_users", "add_evolution_tools", "add_inbox_watches", "add_release", "add_reading",
                  "add_writing", "add_source_created_at", "add_evo_topic_origin"]
LEGACY_STATEMENTS = ["CREATE INDEX IF NOT EXISTS ix_evo_papers_s2_paper_id ON evo_papers (s2_paper_id)"]


def alembic_config(connection=None) -> Config:
    """alembic.ini, with the connection to run on (alembic/env.py uses it instead of opening its own)."""
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def upgrade() -> None:
    """Bring the database to the newest revision, stamping a database made before Alembic first."""
    with engine.connect() as conn:
        postgres = conn.dialect.name == "postgresql"
        if postgres:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
            conn.commit()
        try:
            tables = set(inspect(conn).get_table_names())
            conn.commit()
            if "alembic_version" not in tables and "content_items" in tables:
                from_before_alembic(conn)
            command.upgrade(alembic_config(conn), "head")
            conn.commit()
        finally:
            if postgres:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                conn.commit()


def from_before_alembic(conn) -> None:
    """Run the old migrations one last time, then mark the database as at the baseline."""
    from athena.core.models import Base
    logger.info("Database made before Alembic: running the old migrations once, then stamping the baseline.")
    Base.metadata.create_all(bind=engine)
    for name in LEGACY_SCRIPTS:
        importlib.import_module(f"athena.api.migrations.{name}").run_migration()
    if conn.dialect.name == "postgresql":
        with engine.begin() as c:
            for stmt in LEGACY_STATEMENTS:
                c.execute(text(stmt))
    command.stamp(alembic_config(conn), BASELINE)
    conn.commit()
    logger.info(f"Database stamped with the Alembic baseline ({BASELINE}).")
