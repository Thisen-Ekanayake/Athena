# Documentation for `athena/api/routers/sources.py`

## Overview
Athena Layer 5 — Sources Router

GET   /api/v1/sources             — list all sources (sorted by name)
POST  /api/v1/sources             — preview a source, or add it (two-step flow)
PATCH /api/v1/sources/{id}        — update a source's name and/or URL
PUT   /api/v1/sources/{id}/toggle — enable/disable a source

## Functions
### `_to_response`
Serialise a `Source` ORM row into the `SourceResponse` model (shared by the
list and update endpoints). Includes `created_at` so the UI can sort by date.

### `list_sources`
Returns all sources with authority score, last fetch time, and `created_at`.
Optional `type` / `added_by` query filters. (Sorting by name / date created /
health / protocol / inertia is done client-side in the Settings UI.)

### `add_source`
Two-step add flow keyed on the `confirm` flag of `SourceCreateRequest`:
- `confirm=false` (default) — auto-detect the type and return a preview
  (`source_type`, `source_name`, `sample_items`) **without** writing anything.
- `confirm=true` — persist the source and queue its first crawl.
Returns 400 if the URL can't be reached.

### `update_source`
Update a source's display name and/or URL. Changing the URL re-detects the
source type (best-effort) so the right scraper runs next crawl, and returns
409 if the new URL collides with another source.

### `toggle_source`
Toggle a source's is_active status (enable/disable).
