"""indexes for the feed and the maps' cache key

The feed tables had none beyond their primary keys: the indexes of the old athena/api/migrations/add_indexes.py
were never part of the baseline. Every feed page read all of item_links (430,000 rows) to count related items
and all of content_items to order them; opening an item read all of evo_papers to find its map paper; and every
map request counted evo_citation_contexts for its cache key.

Measured on the 10,000-item database of 2026-11-11 (EXPLAIN ANALYZE, warm): related counts 9.6 -> 0.06 ms, an
item's related items 7.7 -> 0.0 ms, newest first 11.3 -> 0.01 ms, the score order 10.3 -> 1.8 ms, one source or
one cluster 7-10 -> 0.02-0.7 ms, an item's map paper 5.3 -> 0.0 ms, a score breakdown 2.9 -> 0.01 ms, the maps'
labels version 8.5 -> 4 ms. They take about 24 MB, 17 of it for item_links.

Plain ascending columns: Postgres reads an index backwards for "newest first" and "highest first".

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-11 12:00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ('ix_content_items_published_at', 'content_items', ['published_at']),
    ('ix_content_items_score', 'content_items', ['score', 'id', 'source_id']),
    ('ix_content_items_source', 'content_items', ['source_id', 'published_at']),
    ('ix_content_items_cluster', 'content_items', ['cluster_id', 'score']),
    ('ix_item_links_source', 'item_links', ['source_item_id', 'similarity_score']),
    ('ix_content_scores_item', 'content_scores', ['item_id', 'computed_at']),
    ('ix_evo_papers_content_item_id', 'evo_papers', ['content_item_id']),
    ('ix_evo_citation_contexts_labelled_at', 'evo_citation_contexts', ['labelled_at']),
]
# The same indexes under the old script's names, on a database where someone ran it by hand
SUPERSEDED = ['idx_content_score', 'idx_content_date', 'idx_content_cluster', 'idx_content_source',
              'idx_item_links_source']


def upgrade() -> None:
    """Upgrade schema."""
    for name in SUPERSEDED:
        op.execute(f'DROP INDEX IF EXISTS {name}')
    # if_not_exists: a database from before Alembic got today's models, indexes included, from create_all
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
