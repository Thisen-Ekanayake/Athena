"""
Athena — shared Redis client with module-level connection pooling.

Prevents the per-call socket setup/teardown that results from scattered
``redis.from_url(...)`` calls. Two pools are memoised so callers that need
raw bytes and callers that want decoded strings can share sockets safely.
"""
import os
from functools import lru_cache

import redis as redis_lib


DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _redis_url() -> str:
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


@lru_cache(maxsize=2)
def _get_pool(decode_responses: bool) -> redis_lib.ConnectionPool:
    return redis_lib.ConnectionPool.from_url(
        _redis_url(), decode_responses=decode_responses
    )


def get_redis(decode_responses: bool = False) -> redis_lib.Redis:
    """Return a Redis client backed by a shared connection pool."""
    return redis_lib.Redis(connection_pool=_get_pool(decode_responses))


def reset_pools() -> None:
    """Drop cached pools (useful for tests that swap REDIS_URL at runtime)."""
    _get_pool.cache_clear()
