"""drop the Q&A usage log

Q&A tokens and cost are counted in usage_events, and the daily limits use Redis. The rest of qa_usage_log (fetch
method, latency, partial text) was read only by /admin/qa/sessions, which nothing called; both go.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17 23:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if 'qa_usage_log' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('qa_usage_log')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('qa_usage_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('turn_number', sa.Integer(), nullable=False),
    sa.Column('question_length', sa.Integer(), nullable=True),
    sa.Column('fetch_method', sa.String(), nullable=False),
    sa.Column('fetch_latency_ms', sa.Integer(), nullable=True),
    sa.Column('article_tokens', sa.Integer(), nullable=True),
    sa.Column('history_tokens', sa.Integer(), nullable=True),
    sa.Column('answer_tokens', sa.Integer(), nullable=True),
    sa.Column('total_cost_usd', sa.Float(), nullable=True),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('partial_content', sa.Boolean(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=True),
    sa.Column('error_type', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['content_items.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
