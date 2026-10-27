"""pin and archive chats

A pinned chat lists first; an archived one leaves the lists until it is unarchived. Two nullable columns.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A database from before Alembic got today's models from create_all before it was stamped 0001.
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('conversations')}
    if 'pinned_at' not in columns:
        op.add_column('conversations', sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True))
    if 'archived_at' not in columns:
        op.add_column('conversations', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'archived_at')
    op.drop_column('conversations', 'pinned_at')
