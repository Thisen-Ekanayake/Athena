"""drop trending briefs

The daily brief needed trending items, and no item was ever trending, so none was written. The table goes, and
so do its prompt and the TRENDING_BRIEF job type (rows using it, then the value itself from the Postgres enum).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 21:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_TYPES = ('ITEM_SUMMARY', 'CLUSTER_LABEL', 'QA')
JOB_TYPE_COLUMNS = (('prompt_versions', 'job_type'), ('summary_usage_log', 'job_type'))


def upgrade() -> None:
    """Upgrade schema."""
    tables = sa.inspect(op.get_bind()).get_table_names()
    for table, column in JOB_TYPE_COLUMNS:
        if table in tables:
            op.execute(f"DELETE FROM {table} WHERE {column} = 'TRENDING_BRIEF'")
    if 'trending_briefs' in tables:
        op.drop_table('trending_briefs')
    if op.get_bind().dialect.name == "postgresql":
        # Postgres can't drop an enum value: make the type again without it
        op.execute("ALTER TYPE jobtype RENAME TO jobtype_old")
        op.execute("CREATE TYPE jobtype AS ENUM (" + ", ".join(f"'{v}'" for v in JOB_TYPES) + ")")
        for table, column in JOB_TYPE_COLUMNS:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE jobtype USING {column}::text::jobtype")
        op.execute("DROP TYPE jobtype_old")


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'TRENDING_BRIEF' AFTER 'CLUSTER_LABEL'")
    op.create_table('trending_briefs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('category', postgresql.ENUM('PAPER', 'COMPANY_BLOG', 'COMMUNITY_BLOG', name='contentcategory',
                                          create_type=False), nullable=False),
    sa.Column('brief', sa.String(), nullable=False),
    sa.Column('theme', sa.String(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('prompt_version', sa.Integer(), nullable=False),
    sa.Column('source_item_ids', sa.ARRAY(sa.UUID()), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
