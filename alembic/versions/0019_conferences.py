"""conferences

The ACL family's proceedings from the ACL Anthology (athena/conferences/): volumes and the venues they count for,
papers with their topic, awards and citations, the fixed topic list, and each venue's rising terms and summary per
year.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-07 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A database from before Alembic got today's models from create_all before it was stamped 0001.
    if sa.inspect(op.get_bind()).has_table('conf_papers'):
        return
    op.create_table(
        'conf_volumes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('paper_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conf_volumes_year'), 'conf_volumes', ['year'], unique=False)
    op.create_table(
        'conf_volume_venues',
        sa.Column('volume_id', sa.String(), nullable=False),
        sa.Column('venue', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['volume_id'], ['conf_volumes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('volume_id', 'venue'),
    )
    op.create_index(op.f('ix_conf_volume_venues_venue'), 'conf_volume_venues', ['venue'], unique=False)
    op.create_table(
        'conf_topics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('vector', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('vector_model', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'conf_papers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('volume_id', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('abstract', sa.String(), nullable=True),
        sa.Column('abstract_from', sa.String(), nullable=True),
        sa.Column('authors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('doi', sa.String(), nullable=True),
        sa.Column('awards', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('award_rank', sa.Integer(), nullable=True),
        sa.Column('citation_count', sa.Integer(), nullable=True),
        sa.Column('citations_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('topic_id', sa.Integer(), nullable=True),
        sa.Column('topic_score', sa.Float(), nullable=True),
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('embed_model', sa.String(), nullable=True),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['content_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['topic_id'], ['conf_topics.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['volume_id'], ['conf_volumes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conf_papers_award_rank'), 'conf_papers', ['award_rank'], unique=False)
    op.create_index(op.f('ix_conf_papers_topic_id'), 'conf_papers', ['topic_id'], unique=False)
    op.create_index(op.f('ix_conf_papers_volume_id'), 'conf_papers', ['volume_id'], unique=False)
    op.create_index(op.f('ix_conf_papers_year'), 'conf_papers', ['year'], unique=False)
    op.create_table(
        'conf_terms',
        sa.Column('venue', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('term', sa.String(), nullable=False),
        sa.Column('papers', sa.Integer(), nullable=False),
        sa.Column('share', sa.Float(), nullable=False),
        sa.Column('prev_share', sa.Float(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('venue', 'year', 'term'),
    )
    op.create_table(
        'conf_summaries',
        sa.Column('venue', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('stats_hash', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('written_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('venue', 'year'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('conf_summaries')
    op.drop_table('conf_terms')
    op.drop_index(op.f('ix_conf_papers_year'), table_name='conf_papers')
    op.drop_index(op.f('ix_conf_papers_volume_id'), table_name='conf_papers')
    op.drop_index(op.f('ix_conf_papers_topic_id'), table_name='conf_papers')
    op.drop_index(op.f('ix_conf_papers_award_rank'), table_name='conf_papers')
    op.drop_table('conf_papers')
    op.drop_table('conf_topics')
    op.drop_index(op.f('ix_conf_volume_venues_venue'), table_name='conf_volume_venues')
    op.drop_table('conf_volume_venues')
    op.drop_index(op.f('ix_conf_volumes_year'), table_name='conf_volumes')
    op.drop_table('conf_volumes')
