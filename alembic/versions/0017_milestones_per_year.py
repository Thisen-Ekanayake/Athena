"""at most three milestones a year

A map could pick five or six milestones in one busy year (the global top, the era quota and the main path add
up). Builds now keep the three highest-scoring automatic picks per year (TopicConfig.max_milestones_per_year);
this applies the same cap to maps already built. Pins (evo_milestone_overrides) are left alone.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31 12:00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PER_YEAR = 3


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"""
        UPDATE evo_topic_papers SET is_milestone_auto = false
        WHERE id IN (
            SELECT id FROM (
                SELECT tp.id, row_number() OVER (
                    PARTITION BY tp.topic_id, p.year ORDER BY tp.milestone_score DESC, tp.paper_id) AS rank
                FROM evo_topic_papers tp JOIN evo_papers p ON p.id = tp.paper_id
                WHERE tp.is_milestone_auto
            ) ranked
            WHERE rank > {PER_YEAR}
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # The dropped picks come back with the map's next build.
