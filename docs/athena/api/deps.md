# Documentation for `athena/api/deps.py`

## Overview
Athena Layer 5 — Shared FastAPI Dependencies

DB session, Redis client, and JWT auth middleware.

## Functions
### `get_db`
Yield a SQLAlchemy session per request.

### `get_redis_pool`
No docstring provided.

### `get_redis`
Return a Redis client from the connection pool.

### `get_current_user`
Validate JWT token if present. Returns the decoded payload.
For now this is optional — endpoints work without auth.

### `get_current_user_required`
Validate JWT token; raises 401 if missing or invalid.

