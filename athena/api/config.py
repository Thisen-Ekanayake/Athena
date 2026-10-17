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

    # Where the web app is served from; sessions and shared map links need it to be allowed (comma-separated)
    CORS_ORIGINS: list[str] = [o.strip().rstrip("/") for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]

    # Swagger / ReDoc and the OpenAPI schema: off unless switched on; DOCS_PASSWORD puts them behind Basic Auth
    DOCS_ENABLED: bool = os.getenv("DOCS_ENABLED", "false").lower() == "true"
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

    # Qdrant collection the embedding worker fills (athena.pipeline.embedding_worker.COLLECTION_NAME)
    QDRANT_COLLECTION: str = os.getenv(
        "QDRANT_COLLECTION", "athena_content"
    )


settings = Settings()
