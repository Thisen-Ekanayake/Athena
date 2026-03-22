"""
Athena Layer 5 — Shared FastAPI Dependencies

DB session, Redis client, and JWT auth middleware.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import redis as redis_lib
import jose
from jose import jwt

from athena.database.db import SessionLocal
from athena.api.config import settings

# ── DB Session ──────────────────────────────────────────

def get_db():
    """Yield a SQLAlchemy session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Redis Client ────────────────────────────────────────

_redis_pool: redis_lib.ConnectionPool | None = None


def get_redis_pool() -> redis_lib.ConnectionPool:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis_lib.ConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _redis_pool


def get_redis() -> redis_lib.Redis:
    """Return a Redis client from the connection pool."""
    pool = get_redis_pool()
    return redis_lib.Redis(connection_pool=pool)


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
