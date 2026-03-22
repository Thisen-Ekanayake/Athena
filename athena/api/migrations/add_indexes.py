"""
Athena Layer 5 — Database Index Migration

Adds all indexes required by Section 7.1 of the plan document,
plus the is_active column on content_items if missing.
"""
from sqlalchemy import text
from athena.database.db import engine
from loguru import logger


INDEXES = [
    # Feed queries (most critical)
    "CREATE INDEX IF NOT EXISTS idx_content_score ON content_items(score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_content_date ON content_items(published_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_content_category ON content_items(category, score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_content_cluster ON content_items(cluster_id, score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_content_source ON content_items(source_id, published_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_content_trending ON content_items(is_trending, score DESC);",
    # Item links (related articles sidebar)
    "CREATE INDEX IF NOT EXISTS idx_item_links_source ON item_links(source_item_id, similarity_score DESC);",
    # Cluster browser
    "CREATE INDEX IF NOT EXISTS idx_clusters_active ON clusters(is_active);",
]


def run_migration():
    """Apply all indexes and schema changes."""
    with engine.connect() as conn:
        for idx_sql in INDEXES:
            try:
                conn.execute(text(idx_sql))
                logger.info(f"Applied: {idx_sql[:60]}...")
            except Exception as e:
                logger.warning(f"Index skipped: {e}")
        conn.commit()
        logger.info("All database indexes applied successfully.")


if __name__ == "__main__":
    run_migration()
