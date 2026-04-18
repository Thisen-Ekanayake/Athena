"""
Athena Layer 5 — Shared FastAPI Dependencies

DB session, Redis client, and JWT auth middleware.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import redis as redis_lib
import jose
from jose import jwt

from athena.database.db import SessionLocal
from athena.api.config import settings
from athena.core.redis_client import get_redis as _shared_get_redis

# ── DB Session ──────────────────────────────────────────


def get_db():
    """Yield a SQLAlchemy session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Redis Client ────────────────────────────────────────


def get_redis() -> redis_lib.Redis:
    """Return a Redis client from the shared connection pool."""
    return _shared_get_redis(decode_responses=True)


# ── JWT Auth (optional — single shared token for now) ───

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    """
    Validate JWT token if present. Returns the decoded payload.
    For now this is optional — endpoints work without auth.
    """
    if credentials is None:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jose.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


def get_current_user_required(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Validate JWT token; raises 401 if missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials missing",
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jose.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
