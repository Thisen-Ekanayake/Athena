# Documentation for `athena/pipeline/scoring.py`

## Overview
Athena Layer 3 — Scoring Worker

Celery tasks for computing, persisting, and updating content scores.
Consumes items from the Redis scoring queue (emitted after Layer 2 embedding).

## Functions
### `_get_openai_client`
Lazy-load OpenAI client.

### `_get_weights`
Fetch active scoring config weights for the given category, or use defaults.

### `_get_prev_snapshot`
Get previous metric snapshot from ~7 days ago for velocity computation.

### `score_item`
Full scoring pipeline for a single item.
Computes all 5 signals, composite score, trending status, and persists results.

### `update_category_ranks`
Refresh category_rank for all active items using SQL RANK() window function.

### `_get_celery_app`
Lazy import to avoid circular dependency.

### `process_scoring_queue`
Pull items from the scoring queue and score them.

### `score_all_items`
Batch re-score all items (triggered by config change or enrichment refresh).

### `refresh_recency_scores`
Periodic task: recency scores drift as time passes — recompute for all scored items.

### `take_metric_snapshot`
Daily snapshot: capture current citation_count + engagement for velocity computation.

### `score_new_item`
Score a single newly embedded item and update ranks.

### `enqueue_summary_tier`
Emits the item to the correct Celery queue based on Layer 3 score.

### `populate_default_scoring_config`
Populate the scoring_config table with default weight profiles.

### `populate_default_authority_scores`
Assign authority_score to all existing sources based on URL keywords.

