"""
Alembic environment: the models in athena.core.models against DATABASE_URL (athena.database.db).

athena.database.migrate passes the connection it holds the migration lock on as config.attributes["connection"];
the alembic command line connects by itself.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from athena.core.models import Base
from athena.database.db import DATABASE_URL

config = context.config
passed_connection = config.attributes.get("connection")
if config.config_file_name is not None and passed_connection is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)  # the app keeps its own logging

target_metadata = Base.metadata

# Postgres-only full-text search (athena.search.hybrid) that the models leave out; revisions manage it by hand.
HAND_MANAGED = {("column", "search_vector"), ("index", "ix_content_items_search")}


def include_object(obj, name, type_, reflected, compare_to):
    return (type_, name) not in HAND_MANAGED


def configure(**kwargs):
    context.configure(target_metadata=target_metadata, include_object=include_object, **kwargs)


def run_migrations_offline() -> None:
    """Write the SQL instead of running it (alembic upgrade head --sql)."""
    configure(url=DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_on(connection) -> None:
    # SQLite (tests) stores the Postgres types as JSON, so comparing types there would only report noise
    configure(connection=connection, compare_type=connection.dialect.name != "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if passed_connection is not None:
        run_on(passed_connection)
        return
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_on(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
