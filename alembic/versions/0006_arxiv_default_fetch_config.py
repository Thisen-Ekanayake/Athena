"""arXiv source: follow the scraper's query and limit

The crawl now reads a source's fetch_config, and the arXiv row seeded before had {"query": "cat:cs.AI OR
cat:cs.LG", "max_results": 20}, which the crawl never used. Left in place, it would cut each sync to 20 papers in
two categories. Exactly that seeded value is cleared, so the source follows athena.scrapers.arxiv (five
categories, up to 1000 a sync); a config someone changed by hand stays.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 21:40:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARXIV_URL = "https://export.arxiv.org/api/query"
OLD_SEED = '{"query": "cat:cs.AI OR cat:cs.LG", "max_results": 20}'


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"UPDATE sources SET fetch_config = '{{}}'::jsonb "
                   f"WHERE url = '{ARXIV_URL}' AND fetch_config = '{OLD_SEED}'::jsonb")


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"UPDATE sources SET fetch_config = '{OLD_SEED}'::jsonb "
                   f"WHERE url = '{ARXIV_URL}' AND fetch_config = '{{}}'::jsonb")
