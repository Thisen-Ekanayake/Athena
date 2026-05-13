"""
Athena Layer 5 — Centralised Configuration

All environment variables in one place using pydantic-settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://athena:athena_password@localhost:5432/athena_db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "athena-dev-secret-change-me")
    JWT_ALGORITHM: str = "HS256"

    # Swagger / ReDoc access control
    DOCS_ENABLED: bool = os.getenv("DOCS_ENABLED", "true").lower() == "true"
    DOCS_USERNAME: str = os.getenv("DOCS_USERNAME", "athena")
    DOCS_PASSWORD: str = os.getenv("DOCS_PASSWORD", "")

    # Cache TTLs (seconds)
    CACHE_FEED_SCORE_TTL: int = 300       # 5 minutes
    CACHE_FEED_DATE_TTL: int = 900        # 15 minutes
    CACHE_TRENDING_TTL: int = 1800        # 30 minutes
    CACHE_CLUSTERS_TTL: int = 3600        # 1 hour
    CACHE_CLUSTER_DETAIL_TTL: int = 900   # 15 minutes
    CACHE_ITEM_TTL: int = 86400           # 24 hours

    # Pagination defaults
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 50

    # Qdrant collection name
    QDRANT_COLLECTION: str = os.getenv(
        "QDRANT_COLLECTION", "athena_embeddings"
    )


settings = Settings()
