"""drop the cross-map gap links (E7)

Cross-map links were run by hand and never shown: on blind samples 3 of 40 addressed their gap, because across
fields the chunks match on generic wording. The table and the gap statements' cross_checked_at go. Loose links
inside one map (evo_loose_links) stay.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17 23:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    insp = sa.inspect(op.get_bind())
    if 'evo_cross_links' in insp.get_table_names():
        op.drop_index(op.f('ix_evo_cross_links_paper_id'), table_name='evo_cross_links')
        op.drop_index(op.f('ix_evo_cross_links_gap_id'), table_name='evo_cross_links')
        op.drop_table('evo_cross_links')
    if 'cross_checked_at' in {c['name'] for c in insp.get_columns('evo_gap_statements')}:
        with op.batch_alter_table('evo_gap_statements') as batch:
            batch.drop_column('cross_checked_at')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('evo_gap_statements') as batch:
        batch.add_column(sa.Column('cross_checked_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('evo_cross_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('gap_id', sa.UUID(), nullable=False),
    sa.Column('paper_id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['gap_id'], ['evo_gap_statements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_id'], ['evo_papers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gap_id', 'paper_id', name='uq_evo_cross_link')
    )
    op.create_index(op.f('ix_evo_cross_links_gap_id'), 'evo_cross_links', ['gap_id'], unique=False)
    op.create_index(op.f('ix_evo_cross_links_paper_id'), 'evo_cross_links', ['paper_id'], unique=False)
