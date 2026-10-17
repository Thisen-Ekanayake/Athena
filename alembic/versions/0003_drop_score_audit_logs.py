"""drop the score audit log

score_audit_logs was written when a rescore moved an item's score by more than 0.1, and never read.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 21:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if 'score_audit_logs' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('score_audit_logs')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('score_audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('old_score', sa.Float(), nullable=False),
    sa.Column('new_score', sa.Float(), nullable=False),
    sa.Column('delta', sa.Float(), nullable=False),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['content_items.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
