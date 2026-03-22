# Documentation for `athena/api/routers/feed.py`

## Overview
Athena Layer 5 — Feed Router

GET /api/v1/feed — paginated, sorted, filtered content feed.

## Functions
### `_build_feed_item`
Convert a ContentItem ORM object to a FeedItemResponse-compatible dict.

### `get_feed`
Returns a paginated, sorted list of content cards.
The primary endpoint for the main feed.

