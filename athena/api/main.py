"""
Athena Layer 5 — Unified FastAPI Application

Entry point that mounts all API routers, configures CORS,
and wires up DB + Redis connections.
"""
import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from loguru import logger

from athena.api.routers import feed, items, clusters, trending, search, sources, sync, app_settings
from athena.api import qa_api
from athena.api import score_api
from athena.api import summary_api
from athena.api.config import settings

_basic_auth = HTTPBasic()


def _verify_docs_credentials(credentials: HTTPBasicCredentials = Depends(_basic_auth)):
    """Reject requests to /docs or /redoc unless credentials match DOCS_USERNAME/PASSWORD."""
    ok_user = secrets.compare_digest(credentials.username, settings.DOCS_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, settings.DOCS_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from athena.database.db import init_db
        init_db()
        yield

    # Disable built-in docs; we mount our own routes with auth below.
    app = FastAPI(
        lifespan=lifespan,
        title="Athena API",
        description=(
            "AI Research Intelligence Feed — "
            "Layer 5 API serving content cards, clusters, "
            "search, and source management."
        ),
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )

    # ── CORS ────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Docs (optional, Basic-Auth-gated) ───────────────
    if settings.DOCS_ENABLED:
        if settings.DOCS_PASSWORD:
            # Password set → protect with HTTP Basic Auth
            @app.get("/docs", include_in_schema=False)
            def swagger_ui(credentials: HTTPBasicCredentials = Depends(_verify_docs_credentials)):
                return get_swagger_ui_html(openapi_url="/openapi.json", title="Athena API")

            @app.get("/redoc", include_in_schema=False)
            def redoc_ui(credentials: HTTPBasicCredentials = Depends(_verify_docs_credentials)):
                return get_redoc_html(openapi_url="/openapi.json", title="Athena API")
        else:
            # No password → open access (dev default)
            @app.get("/docs", include_in_schema=False)
            def swagger_ui_open():
                return get_swagger_ui_html(openapi_url="/openapi.json", title="Athena API")

            @app.get("/redoc", include_in_schema=False)
            def redoc_ui_open():
                return get_redoc_html(openapi_url="/openapi.json", title="Athena API")

    # ── Routers ─────────────────────────────────────────
    app.include_router(feed.router)
    app.include_router(items.router)
    app.include_router(clusters.router)
    app.include_router(trending.router)
    app.include_router(search.router)
    app.include_router(sources.router)
    app.include_router(sync.router)
    app.include_router(app_settings.router)
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
