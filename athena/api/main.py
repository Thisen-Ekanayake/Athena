"""
The FastAPI application

Entry point that mounts all API routers, configures CORS,
and wires up DB + Redis connections.
"""
import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from loguru import logger

from athena.api.routers import (
    feed, items, clusters, search, sources, sync, app_settings, saved, evolution, inbox, auth as auth_routes,
    users, watches, usage, share, momentum, personal, interests, reviews, scoring, summaries, projects, chats,
)
from athena.api import qa_api
from athena.api.auth import active_user, require_admin
from athena.api.config import settings

_basic_auth = HTTPBasic()


def _verify_docs_credentials(credentials: HTTPBasicCredentials = Depends(_basic_auth)):
    """Reject requests to /docs, /redoc or /openapi.json unless credentials match DOCS_USERNAME/PASSWORD."""
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

    # Disable built-in docs and schema; we mount our own routes with auth below.
    app = FastAPI(
        lifespan=lifespan,
        title="Athena API",
        description=(
            "AI Research Intelligence Feed — "
            "Athena's API: the feed, clusters, search, research maps, "
            "reading tools and accounts."
        ),
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # ── CORS ────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Docs (off unless DOCS_ENABLED; Basic-Auth-gated when DOCS_PASSWORD is set) ──
    if settings.DOCS_ENABLED:
        if settings.DOCS_PASSWORD:
            docs_guard = [Depends(_verify_docs_credentials)]
        else:
            docs_guard = []
            logger.warning("DOCS_ENABLED is on without DOCS_PASSWORD: /docs, /redoc and /openapi.json are open "
                           "to anyone who can reach the API.")

        @app.get("/openapi.json", include_in_schema=False, dependencies=docs_guard)
        def openapi_schema():
            return JSONResponse(app.openapi())

        @app.get("/docs", include_in_schema=False, dependencies=docs_guard)
        def swagger_ui():
            return get_swagger_ui_html(openapi_url="/openapi.json", title="Athena API")

        @app.get("/redoc", include_in_schema=False, dependencies=docs_guard)
        def redoc_ui():
            return get_redoc_html(openapi_url="/openapi.json", title="Athena API")

    # ── Routers ─────────────────────────────────────────
    # Every route needs a logged-in account, except logging in itself, shared map links and /health.
    # Admin-only routes add require_admin themselves (see routers/users.py, sources.py, evolution.py, ...).
    login = [Depends(active_user)]
    admin = [Depends(require_admin)]
    app.include_router(auth_routes.router)
    app.include_router(users.router)
    app.include_router(feed.router, dependencies=login)
    app.include_router(items.router, dependencies=login)
    app.include_router(momentum.router, dependencies=login)
    app.include_router(personal.router, dependencies=login)
    app.include_router(interests.router, dependencies=login)
    app.include_router(reviews.router, dependencies=login)
    app.include_router(projects.router, dependencies=login)
    app.include_router(chats.router, dependencies=login)
    app.include_router(clusters.router, dependencies=login)
    app.include_router(search.router, dependencies=login)
    app.include_router(sources.router, dependencies=login)
    app.include_router(sync.router, dependencies=login)  # starting one is for admins; the route says so
    app.include_router(app_settings.router, dependencies=admin)
    app.include_router(saved.router, dependencies=login)
    app.include_router(evolution.router, dependencies=login)
    app.include_router(inbox.router, dependencies=login)
    app.include_router(watches.router, dependencies=login)
    app.include_router(usage.router, dependencies=login)  # the admin views add require_admin themselves
    app.include_router(share.router)  # read-only maps behind a share link; the token is the access
    app.include_router(qa_api.router, prefix="/api/v1", tags=["QA"], dependencies=login)
    app.include_router(scoring.router, dependencies=login)  # rescore-all adds require_admin itself
    app.include_router(summaries.router, dependencies=login)  # the admin views add require_admin themselves

    # ── Health check ────────────────────────────────────
    @app.get("/health", tags=["Health"])
    def health_check():
        return {"status": "ok", "service": "athena-api"}

    logger.info("Athena API application created successfully")
    return app


# Module-level app instance for uvicorn
app = create_app()
