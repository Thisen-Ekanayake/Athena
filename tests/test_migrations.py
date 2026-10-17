"""Alembic (ROADMAP_v2 B3): the revisions build the schema the models describe, and old databases get stamped."""
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from athena.core.models import Base, ContentItem
from athena.database import migrate


@pytest.fixture
def sqlite_engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'athena.db'}")
    monkeypatch.setattr(migrate, "engine", engine)
    yield engine
    engine.dispose()


def _revision(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _head():
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()


def test_a_new_database_matches_the_models(sqlite_engine):
    """A model change without a revision fails here: write one with alembic revision --autogenerate."""
    migrate.upgrade()
    assert _revision(sqlite_engine) == _head()
    with sqlite_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
    assert diff == []


def test_upgrading_again_changes_nothing(sqlite_engine):
    migrate.upgrade()
    migrate.upgrade()
    assert _revision(sqlite_engine) == _head()


def test_a_database_from_before_alembic_is_stamped_first(sqlite_engine, monkeypatch):
    ContentItem.__table__.create(sqlite_engine)  # what create_all left behind, without alembic_version
    ran = []

    def old_migrations(conn):
        ran.append(True)
        Base.metadata.create_all(bind=sqlite_engine)
        from alembic import command
        command.stamp(migrate.alembic_config(conn), migrate.BASELINE)
        conn.commit()

    monkeypatch.setattr(migrate, "from_before_alembic", old_migrations)
    migrate.upgrade()
    assert ran == [True]
    assert _revision(sqlite_engine) == _head()
    migrate.upgrade()
    assert ran == [True]  # stamped databases never run the old scripts again


def test_a_new_database_skips_the_old_migrations(sqlite_engine, monkeypatch):
    monkeypatch.setattr(migrate, "from_before_alembic", lambda conn: pytest.fail("ran the old migrations"))
    migrate.upgrade()
    assert "content_items" in inspect(sqlite_engine).get_table_names()


def test_sentiment_weight_is_spread_over_the_other_signals(sqlite_engine):
    """0002: an active saved profile with a sentiment share gets a new version without it, still adding up to 1."""
    from alembic import command
    with sqlite_engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0001")
        conn.execute(text(
            "INSERT INTO scoring_config (id, version, category, weight_citation, weight_engagement, weight_sentiment,"
            " weight_recency, weight_authority, weight_preference, half_life_days, is_active)"
            " VALUES ('a', 7, 'PAPER', 0.3, 0.15, 0.15, 0.2, 0.2, 0.4, 60, 1)"))
        conn.commit()
    migrate.upgrade()
    with sqlite_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT version, is_active, weight_citation, weight_engagement, weight_recency, weight_authority,"
            " weight_preference, half_life_days FROM scoring_config ORDER BY version")).all()
    assert [(r[0], bool(r[1])) for r in rows] == [(7, False), (8, True)]
    new = rows[1]
    assert new[2:6] == pytest.approx((0.3 / 0.85, 0.15 / 0.85, 0.2 / 0.85, 0.2 / 0.85))
    assert sum(new[2:6]) == pytest.approx(1) and new[6:] == (0.4, 60)
