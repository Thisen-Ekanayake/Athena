# Documentation for `athena/api/routers/items.py`

## Overview
Athena Layer 5 — Items Router

GET /api/v1/items/{id}                — single item with full detail
GET /api/v1/items/{id}/score-breakdown — score explainability
GET /api/v1/items/{id}/related        — nearest-neighbour items

## Functions
### `get_item`
Returns a single content item with full detail.
Triggers on-demand summarisation if summary_status = lazy.

### `get_score_breakdown`
Returns the full per-signal score breakdown for the
score tooltip on hover.

### `get_related_items`
Returns the nearest-neighbour items from item_links.
Used for the related articles sidebar.

