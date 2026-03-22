"""
Athena Layer 5 — Redis Caching Utilities

Simple get/set/invalidate wrappers with JSON serialisation.
"""
import json
from typing import Any
import redis as redis_lib
from loguru import logger


def cache_get(r: redis_lib.Redis, key: str) -> Any | None:
    """Retrieve a cached value. Returns None on miss or error."""
    try:
        raw = r.get(key)
        if raw is not None:
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Cache GET failed for {key}: {e}")
    return None


def cache_set(
    r: redis_lib.Redis, key: str, value: Any, ttl: int = 300
) -> None:
    """Store a value in cache with a TTL (seconds)."""
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as e:
        logger.warning(f"Cache SET failed for {key}: {e}")


def cache_invalidate(r: redis_lib.Redis, pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    try:
        keys = list(r.scan_iter(match=pattern, count=100))
        if keys:
            return r.delete(*keys)
    except Exception as e:
        logger.warning(f"Cache INVALIDATE failed for {pattern}: {e}")
    return 0
