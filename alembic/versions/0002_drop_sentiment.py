"""drop the sentiment signal

Sentiment was 0.5 on every score: nothing gave it comments to read. Its weight goes to the other four signals:
each active saved weight profile that gave sentiment a share gets a new version with that share spread over
them in proportion, so the four still sum to 1. Its reference-embedding table (never read) goes with it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 21:00:00

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OTHERS = ("weight_citation", "weight_engagement", "weight_recency", "weight_authority")


def _has(table: str, column: str | None = None) -> bool:
    """Whether the table (or its column) is there. A database from before Alembic gets the tables it lacked from
    today's models before it is stamped with the baseline (athena.database.migrate), so it may be without them."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column is None or column in {c["name"] for c in insp.get_columns(table)}


def _respread_sentiment() -> None:
    """A new active version of each active profile with a sentiment share, that share spread over the others."""
    bind = op.get_bind()
    if not _has("scoring_config", "weight_sentiment"):
        return
    rows = bind.execute(sa.text(
        "SELECT id, category, weight_sentiment, weight_preference, half_life_days, "
        + ", ".join(OTHERS) + " FROM scoring_config WHERE is_active AND coalesce(weight_sentiment, 0) > 0"
    )).mappings().all()
    if not rows:
        return
    version = bind.execute(sa.text("SELECT coalesce(max(version), 0) FROM scoring_config")).scalar()
    for row in rows:
        rest = sum(row[k] or 0 for k in OTHERS)
        # If sentiment had everything, share it equally
        new = {k: ((row[k] or 0) / rest if rest else 1 / len(OTHERS)) for k in OTHERS}
        version += 1
        bind.execute(sa.text("UPDATE scoring_config SET is_active = false WHERE id = :id"), {"id": row["id"]})
        bind.execute(sa.text(
            "INSERT INTO scoring_config (id, version, category, " + ", ".join(OTHERS) + ", weight_sentiment, "
            "weight_preference, half_life_days, is_active, created_at, notes) VALUES (:id, :version, :category, "
            + ", ".join(f":{k}" for k in OTHERS) + ", 0, :pref, :half, true, CURRENT_TIMESTAMP, :notes)"
        ), {"id": str(uuid4()), "version": version,
            "category": row["category"], **new, "pref": row["weight_preference"],
            "half": row["half_life_days"], "notes": "Sentiment removed: its weight spread over the others"})


def upgrade() -> None:
    """Upgrade schema."""
    _respread_sentiment()
    if _has('content_scores', 'sentiment_score'):
        with op.batch_alter_table('content_scores') as batch:
            batch.drop_column('sentiment_score')
    if _has('scoring_config', 'weight_sentiment'):
        with op.batch_alter_table('scoring_config') as batch:
            batch.drop_column('weight_sentiment')
    if _has('reference_embeddings'):
        op.drop_table('reference_embeddings')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('reference_embeddings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('text_content', sa.String(), nullable=False),
    sa.Column('embedding', sa.ARRAY(sa.Float()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('scoring_config') as batch:
        batch.add_column(sa.Column('weight_sentiment', sa.Float(), nullable=True))
    with op.batch_alter_table('content_scores') as batch:
        batch.add_column(sa.Column('sentiment_score', sa.Float(), nullable=True))
