# Documentation for `athena/api/routers/clusters.py`

## Overview
Athena Layer 5 — Clusters Router

GET /api/v1/clusters       — all active clusters with item counts
GET /api/v1/clusters/{id}  — cluster detail + paginated items

## Functions
### `get_clusters`
Returns all active clusters with item count, label, and description.

### `get_cluster_detail`
Returns cluster metadata and top items sorted by score.

