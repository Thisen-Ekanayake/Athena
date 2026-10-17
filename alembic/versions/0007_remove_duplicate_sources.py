"""remove the duplicate sources

Anthropic News, Meta AI Blog and The Gradient each had two rows. The RSS rows of the first two never gave an
item (they failed six syncs in a row), and The Gradient's /rss/ row gave none while the row that has its items was
switched off. Each empty duplicate is deleted, only while it has no items (with its fetch log and any follows), and
The Gradient's row with items is switched back on. Setup no longer seeds the duplicates.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-17 21:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DUPLICATES = ("https://www.anthropic.com/feed.xml", "https://ai.meta.com/blog/rss/", "https://thegradient.pub/rss/")
KEPT = "https://thegradient.pub/"
DEPENDENTS = ("fetch_logs", "quarantine_items", "watches")  # rows that point at a source


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "sources" not in tables:
        return
    for url in DUPLICATES:
        source_id = bind.execute(sa.text(
            "SELECT id FROM sources s WHERE url = :url "
            "AND NOT EXISTS (SELECT 1 FROM content_items i WHERE i.source_id = s.id)"), {"url": url}).scalar()
        if source_id is None:
            continue
        for table in DEPENDENTS:
            if table in tables:
                bind.execute(sa.text(f"DELETE FROM {table} WHERE source_id = :id"), {"id": source_id})
        bind.execute(sa.text("DELETE FROM sources WHERE id = :id"), {"id": source_id})
    bind.execute(sa.text("UPDATE sources SET is_active = true, consecutive_failures = 0 WHERE url = :url"),
                 {"url": KEPT})


def downgrade() -> None:
    """Downgrade schema."""
    pass  # the deleted rows were empty duplicates: nothing to put back
