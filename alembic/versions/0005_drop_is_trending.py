"""drop content_items.is_trending

Trending needed citation and engagement velocity that no item ever reached, so it was always false. Citation
momentum (citation_gain_7d / citation_gain_30d, the Rising page) is the one "rising" measure.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 21:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if 'is_trending' in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('content_items')}:
        with op.batch_alter_table('content_items') as batch:
            batch.drop_column('is_trending')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('content_items') as batch:
        batch.add_column(sa.Column('is_trending', sa.Boolean(), nullable=True))
