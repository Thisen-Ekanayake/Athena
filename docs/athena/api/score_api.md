# Documentation for `athena/api/score_api.py`

## Overview
Athena Layer 3 — Score Breakdown API

FastAPI endpoint for exposing score explainability to the card UI (Layer 5).

## Functions
### `get_db`
No docstring provided.

### `_score_label`
Convert a numeric score to a human-readable label.

### `get_score_breakdown`
Returns the full score breakdown for a content item.

Response shape matches the plan document:
{
    "composite_score": 0.84,
    "is_trending": true,
    "signals": {
        "citation_impact": {"score": 0.91, "label": "Strong", "weight": 0.30},
        ...
    },
    "computed_at": "...",
    "score_version": 3
}

### `get_top_items`
Get top-ranked items in a category.

### `get_trending_items`
Get currently trending items across all categories.

### `trigger_rescore`
Admin endpoint: trigger a full re-score of all items (e.g. after config change).

### `scoring_health`
Scoring health metrics for the dashboard.

### `fetch_health`
Fetch health data for the dashboard.

