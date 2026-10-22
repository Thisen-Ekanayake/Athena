"""drop what old code put back

Code from before a revision, run against a database that already has it, still creates every table it knows,
runs its add_*.py migrations and seeds its sources: create_all only skips what exists. On 2026-10-19 a checkout
from before the Alembic baseline (e765910) and the May images ./run_docker.sh had kept did that here. They brought
back the tables 0002, 0003, 0004, 0009, 0010 and 0011 dropped (empty), the gap statements' cross_checked_at, and
the three duplicate sources 0007 deleted. Two of those feeds answer 404, so every sync stayed open through their
retries and the next one was refused. Everything goes again, the way it went the first time.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-20 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("reference_embeddings", "score_audit_logs", "trending_briefs", "summary_usage_log", "qa_usage_log",
          "evo_cross_links")
DUPLICATES = ("https://www.anthropic.com/feed.xml", "https://ai.meta.com/blog/rss/", "https://thegradient.pub/rss/")
DEPENDENTS = ("fetch_logs", "quarantine_items", "watches")  # rows that point at a source


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in TABLES:
        if table in tables:
            op.drop_table(table)
    if 'evo_gap_statements' in tables and \
            'cross_checked_at' in {c['name'] for c in insp.get_columns('evo_gap_statements')}:
        with op.batch_alter_table('evo_gap_statements') as batch:
            batch.drop_column('cross_checked_at')
    if 'sources' not in tables:
        return
    for url in DUPLICATES:  # as in 0007: a duplicate goes only while it has no items
        empty = bind.execute(sa.text(
            "SELECT id FROM sources s WHERE url = :url "
            "AND NOT EXISTS (SELECT 1 FROM content_items i WHERE i.source_id = s.id)"), {"url": url}).scalars().all()
        for source_id in empty:
            for table in DEPENDENTS:
                if table in tables:
                    bind.execute(sa.text(f"DELETE FROM {table} WHERE source_id = :id"), {"id": source_id})
            bind.execute(sa.text("DELETE FROM sources WHERE id = :id"), {"id": source_id})


def downgrade() -> None:
    """Downgrade schema."""
    pass  # 0011's schema has none of these, and the deleted sources were empty duplicates
