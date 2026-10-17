"""drop the summary usage log

Every model call is counted in usage_events, summaries and cluster labels included, and /admin/summaries/cost
reads it from there. summary_usage_log was a second copy of the same tokens and cost.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if 'summary_usage_log' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('summary_usage_log')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('summary_usage_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=True),
    sa.Column('cluster_id', sa.UUID(), nullable=True),
    sa.Column('job_type', postgresql.ENUM('ITEM_SUMMARY', 'CLUSTER_LABEL', 'QA', name='jobtype', create_type=False),
              nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('prompt_version', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('total_cost_usd', sa.Float(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=True),
    sa.Column('error_message', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['content_items.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
