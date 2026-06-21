# Documentation for `athena/api/schemas.py`

## Overview
Athena Layer 5 — Pydantic v2 Response Schemas

Response models for all API endpoints, matching the plan document Section 3.4.

## Classes
### `SourceInfo`
No docstring provided.

### `ClusterInfo`
No docstring provided.

### `FeedItemResponse`
No docstring provided.

### `PaginationInfo`
No docstring provided.

### `FeedResponse`
No docstring provided.

### `ItemDetailResponse`
No docstring provided.

### `SignalScore`
No docstring provided.

### `ScoreBreakdownResponse`
No docstring provided.

### `RelatedItemResponse`
No docstring provided.

### `ClusterSummaryResponse`
No docstring provided.

### `ClusterDetailResponse`
No docstring provided.

### `TrendingBriefResponse`
No docstring provided.

### `TrendingResponse`
No docstring provided.

### `SearchResultItem`
No docstring provided.

### `SearchResponse`
No docstring provided.

### `SourceResponse`
No docstring provided.

### `SourcePreviewResponse`
Preview payload for a source: `source_type`, `source_name`, `sample_items`
(list of `SourcePreviewItem`), plus optional `id`/`queued` on the confirm step.

### `SourcePreviewItem`
A single preview row: `title`, `url`, `published_at`, `summary`.

### `SourceResponse`
Source list/detail row. Includes `created_at` (for date-created sorting),
`authority_score`, `is_active`, `added_by`, `last_fetched_at`,
`consecutive_failures`.

### `SourceCreateRequest`
Add-source request: `url`, optional `name`/`category`, and a `confirm` flag
(false = preview only, true = persist + queue the first crawl).

### `SourceUpdateRequest`
Update a source's `name` and/or `url` (used by PATCH /sources/{id}).

### `SourceToggleResponse`
No docstring provided.

