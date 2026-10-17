"""
Shared FastAPI dependencies

DB session and Redis client. Accounts and sessions live in athena/api/auth.py.
"""
import redis as redis_lib

from athena.database.db import SessionLocal
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
