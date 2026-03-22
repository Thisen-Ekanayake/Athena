# Documentation for `athena/api/routers/search.py`

## Overview
Athena Layer 5 — Search Router

GET /api/v1/search — semantic search via OpenAI embed + Qdrant ANN.

## Functions
### `_embed_query`
Embed a search query using OpenAI text-embedding-3-small.

### `_qdrant_search`
Run ANN search on Qdrant and return point IDs with scores.

### `search`
Semantic search: embeds the query string server-side and
runs Qdrant ANN search. Returns ranked results.

