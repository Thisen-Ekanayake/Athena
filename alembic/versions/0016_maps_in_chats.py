"""maps in chats

Research maps attached to a chat (conversation_maps), a project map's share switch, the map papers an answer
named (chat_messages.map_refs), and files taken out of a chat's turns (user_files.detached_at).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-28 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    # A database from before Alembic got today's models from create_all before it was stamped 0001.
    if not sa.inspect(op.get_bind()).has_table('conversation_maps'):
        op.create_table(
            'conversation_maps',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('topic_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('share', sa.Boolean(), nullable=False),
            sa.Column('key', sa.String(length=1), nullable=False),
            sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['topic_id'], ['evo_topics.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('conversation_id', 'topic_id', name='uq_conversation_map'),
        )
        op.create_index(op.f('ix_conversation_maps_conversation_id'), 'conversation_maps', ['conversation_id'],
                        unique=False)
    if 'share' not in _columns('project_items'):
        op.add_column('project_items', sa.Column('share', sa.Boolean(), server_default='false', nullable=False))
    if 'map_refs' not in _columns('chat_messages'):
        op.add_column('chat_messages', sa.Column('map_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if 'detached_at' not in _columns('user_files'):
        op.add_column('user_files', sa.Column('detached_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_files', 'detached_at')
    op.drop_column('chat_messages', 'map_refs')
    op.drop_column('project_items', 'share')
    op.drop_index(op.f('ix_conversation_maps_conversation_id'), table_name='conversation_maps')
    op.drop_table('conversation_maps')
