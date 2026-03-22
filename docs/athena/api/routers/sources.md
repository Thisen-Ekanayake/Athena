# Documentation for `athena/api/routers/sources.py`

## Overview
Athena Layer 5 — Sources Router

GET  /api/v1/sources            — list all sources
POST /api/v1/sources            — add source with auto-detect + preview
PUT  /api/v1/sources/{id}/toggle — enable/disable a source

## Functions
### `list_sources`
Returns all sources with authority score and last fetch time.

### `add_source`
User adds a custom source URL.
Triggers auto-detection and test fetch. Returns preview.

### `toggle_source`
Toggle a source's is_active status (enable/disable).

