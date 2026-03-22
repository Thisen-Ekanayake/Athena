# Documentation for `athena/api/cache.py`

## Overview
Athena Layer 5 — Redis Caching Utilities

Simple get/set/invalidate wrappers with JSON serialisation.

## Functions
### `cache_get`
Retrieve a cached value. Returns None on miss or error.

### `cache_set`
Store a value in cache with a TTL (seconds).

### `cache_invalidate`
Delete all keys matching a glob pattern. Returns count deleted.

