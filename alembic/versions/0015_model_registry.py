"""model registry

The GGUF files an admin registers (llm_models), what each measured at each context and device (llm_benchmarks), the
context size a chat picked (conversations.context) and how each answer ran (chat_messages.stats).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-27 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A database from before Alembic got today's models from create_all before it was stamped 0001.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'llm_models' not in tables:
        _create_tables()
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('conversations')}
    if 'context' not in columns:
        op.add_column('conversations', sa.Column('context', sa.Integer(), nullable=True))
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('chat_messages')}
    if 'stats' not in columns:
        op.add_column('chat_messages', sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def _create_tables() -> None:
    op.create_table(
        'llm_models',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('mmproj_path', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('mmproj_bytes', sa.BigInteger(), nullable=True),
        sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('info', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('reasoning', sa.Boolean(), nullable=False),
        sa.Column('tools', sa.Boolean(), nullable=False),
        sa.Column('placement', sa.String(), nullable=False),
        sa.Column('contexts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('default_context', sa.Integer(), nullable=False),
        sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('plans', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'llm_benchmarks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('model_id', sa.UUID(), nullable=False),
        sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('device', sa.String(), nullable=False),
        sa.Column('context', sa.Integer(), nullable=False),
        sa.Column('gpu_layers', sa.Integer(), nullable=True),
        sa.Column('gen_tps', sa.Float(), nullable=True),
        sa.Column('prompt_tps', sa.Float(), nullable=True),
        sa.Column('load_seconds', sa.Float(), nullable=True),
        sa.Column('samples', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['llm_models.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_id', 'fingerprint', 'device', 'context', name='uq_llm_benchmark'),
    )
    op.create_index(op.f('ix_llm_benchmarks_model_id'), 'llm_benchmarks', ['model_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'stats')
    op.drop_column('conversations', 'context')
    op.drop_index(op.f('ix_llm_benchmarks_model_id'), table_name='llm_benchmarks')
    op.drop_table('llm_benchmarks')
    op.drop_table('llm_models')
