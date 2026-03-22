"""
Athena Layer 5 — Unified FastAPI Application

Entry point that mounts all API routers, configures CORS,
and wires up DB + Redis connections.
"""
from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from athena.api.routers import feed, items, clusters, trending, search, sources
from athena.api import qa_api
from athena.api import score_api
from athena.api import summary_api


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Athena API",
        description=(
            "AI Research Intelligence Feed — "
            "Layer 5 API serving content cards, clusters, "
            "search, and source management."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ─────────────────────────────────────────
    app.include_router(feed.router)
    app.include_router(items.router)
    app.include_router(clusters.router)
    app.include_router(trending.router)
    app.include_router(search.router)
    app.include_router(sources.router)
    app.include_router(qa_api.router, prefix="/api/v1", tags=["QA"])
    app.include_router(
        score_api.app.router, prefix="/api/v1",
        tags=["Scoring"],
    )
    app.include_router(
        summary_api.app.router, prefix="/api/v1",
        tags=["Summarisation"],
    )

    # ── Health check ────────────────────────────────────
    @app.get("/health", tags=["Health"])
    def health_check():
        return {"status": "ok", "service": "athena-api"}

    logger.info("Athena API application created successfully")
    return app


# Module-level app instance for uvicorn
app = create_app()
