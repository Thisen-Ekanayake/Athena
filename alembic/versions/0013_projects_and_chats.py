"""projects and chats

Projects gather a user's papers, maps, reviews, idea checks, saved lists, uploaded files, chats and artifacts
(athena.projects). Chats can stand alone; their messages keep the model's thinking, tool calls and cited passages.
Artifacts are Markdown documents with every version kept. New tables only.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A database from before Alembic got today's models from create_all before it was stamped 0001.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'projects' not in tables:
        op.create_table('projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('instructions', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_projects_user_id'), 'projects', ['user_id'], unique=False)
    if 'conversations' not in tables:
        op.create_table('conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('effort', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_conversations_project_id'), 'conversations', ['project_id'], unique=False)
        op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False)
    if 'artifacts' not in tables:
        op.create_table('artifacts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('index_status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_artifacts_conversation_id'), 'artifacts', ['conversation_id'], unique=False)
        op.create_index(op.f('ix_artifacts_project_id'), 'artifacts', ['project_id'], unique=False)
        op.create_index(op.f('ix_artifacts_user_id'), 'artifacts', ['user_id'], unique=False)
    if 'chat_messages' not in tables:
        op.create_table('chat_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('reasoning', sa.String(), nullable=True),
        sa.Column('reasoning_ms', sa.Integer(), nullable=True),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('attachments', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('effort', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_chat_messages_conversation_created', 'chat_messages', ['conversation_id', 'created_at'], unique=False)
    if 'project_items' not in tables:
        op.create_table('project_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('ref', sa.String(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=True),
        sa.Column('paper_id', sa.UUID(), nullable=True),
        sa.Column('topic_id', sa.UUID(), nullable=True),
        sa.Column('review_id', sa.UUID(), nullable=True),
        sa.Column('idea_check_id', sa.UUID(), nullable=True),
        sa.Column('list_id', sa.UUID(), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('index_status', sa.String(), nullable=False),
        sa.Column('index_error', sa.String(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['idea_check_id'], ['evo_idea_checks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['list_id'], ['saved_lists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['paper_id'], ['evo_papers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['review_id'], ['lit_reviews.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['evo_topics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'ref', name='uq_project_item_ref')
        )
        op.create_index(op.f('ix_project_items_project_id'), 'project_items', ['project_id'], unique=False)
    if 'user_files' not in tables:
        op.create_table('user_files',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('mime', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('text', sa.String(), nullable=True),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('pages', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('index_status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_user_files_conversation_id'), 'user_files', ['conversation_id'], unique=False)
        op.create_index(op.f('ix_user_files_project_id'), 'user_files', ['project_id'], unique=False)
        op.create_index(op.f('ix_user_files_user_id'), 'user_files', ['user_id'], unique=False)
    if 'artifact_versions' not in tables:
        op.create_table('artifact_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('artifact_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('author', sa.String(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('artifact_id', 'version', name='uq_artifact_version')
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('artifact_versions')
    op.drop_index(op.f('ix_user_files_user_id'), table_name='user_files')
    op.drop_index(op.f('ix_user_files_project_id'), table_name='user_files')
    op.drop_index(op.f('ix_user_files_conversation_id'), table_name='user_files')
    op.drop_table('user_files')
    op.drop_index(op.f('ix_project_items_project_id'), table_name='project_items')
    op.drop_table('project_items')
    op.drop_index('ix_chat_messages_conversation_created', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index(op.f('ix_artifacts_user_id'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_project_id'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_conversation_id'), table_name='artifacts')
    op.drop_table('artifacts')
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_index(op.f('ix_conversations_project_id'), table_name='conversations')
    op.drop_table('conversations')
    op.drop_index(op.f('ix_projects_user_id'), table_name='projects')
    op.drop_table('projects')
