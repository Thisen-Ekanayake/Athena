"""a SKIPPED summary status

An item with too little text to summarise without inventing details was marked FAILED, the same as a model error,
and a rescore could put it back in the queue as LAZY or PENDING. It now gets SKIPPED, with the reason still in
extra_data.summary_skipped. Items already flagged move to it from FAILED, LAZY or PENDING.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 22:00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _flagged() -> str:
    """SQL for: the item's extra_data has a summary_skipped reason."""
    if op.get_bind().dialect.name == "postgresql":
        return "extra_data ? 'summary_skipped'"
    return "json_extract(extra_data, '$.summary_skipped') IS NOT NULL"


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        # A new enum value can't be used in the transaction that adds it
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE summarystatus ADD VALUE IF NOT EXISTS 'SKIPPED'")
    op.execute("UPDATE content_items SET summary_status = 'SKIPPED' "
               f"WHERE summary_status IN ('FAILED', 'LAZY', 'PENDING') AND {_flagged()}")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres keeps the enum value; nothing uses it once the rows are FAILED again
    op.execute("UPDATE content_items SET summary_status = 'FAILED' WHERE summary_status = 'SKIPPED'")
