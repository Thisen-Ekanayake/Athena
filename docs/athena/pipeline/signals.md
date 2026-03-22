# Documentation for `athena/pipeline/signals.py`

## Overview
Signal computation functions for Athena Layer 3 Scoring & Ranking.

Each function computes a single normalised score in [0.0, 1.0].

## Functions
### `compute_citation_score`
Log-normalised citation impact.

Using log(1 + count) / log(1 + corpus_max) prevents papers with 10k+
citations from drowning all others while still rewarding high citation counts.

### `_extract_engagement_signals`
Extract and normalise engagement signals from metadata based on source platform.

### `compute_engagement_score`
Compute normalised engagement score by extracting platform-specific signals
and averaging them. Returns 0.5 (neutral) if no engagement data is available.

### `_cosine_similarity`
Compute cosine similarity between two vectors.

### `_get_reference_embeddings`
Get or compute reference pole embeddings (cached in module globals).

### `_extract_comments`
Extract comment texts from metadata JSONB.

### `compute_sentiment_score`
Compute semantic sentiment by embedding comments and comparing cosine
similarity to positive/negative reference poles.

Returns 0.5 (neutral) if no comments are available or if embedding fails.

### `compute_recency_score`
Exponential decay based on age. A paper published half_life_days ago scores 0.5.
Formula: score = exp(-λ * age_days) where λ = ln(2) / half_life_days

### `compute_velocity_score`
Velocity = rate of change in citation count + engagement over the last 7 days.
Normalised against reasonable maxima.

### `compute_authority_score`
Pass-through from source.authority_score with null safety.

### `compute_composite_score`
Weighted sum of all 5 signals, clipped to [0.0, 1.0].

weights should contain keys: citation, engagement, sentiment, recency, authority

### `apply_trending_boost`
Trending items receive a +0.08 boost, capped at 0.95.
Keeps truly seminal older work still reachable at top.

### `check_trending_criteria`
Determine if an item qualifies as trending:
- velocity_score > threshold (~top 5%)
- Published within last max_age_days
- Has at least min_engagement_points engagement signals

