# Documentation for `athena/pipeline/clustering.py`

## Overview
Topic clustering pipeline. MLflow tracking is best-effort via
`athena.pipeline.mlflow_utils` — a tracking-server outage no longer blocks the
job (it previously crashed `run_clustering` on the first `mlflow.set_experiment`
call).

## Functions
### `run_clustering`
Main clustering job:
1. Fetch all embeddings from Qdrant
2. Reduce dimensionality with UMAP
3. Group with **K-Means** (k = clamp(num_items // 10, 5, 20))
4. Label with TF-IDF
5. Stability-match against existing clusters (cosine ≥ 0.85 → update; else new)
6. Persist results, deactivate stale clusters, and queue label generation

### `process_clusters`
Assigns each item to its cluster (new or stability-matched), writes
cluster_distance, and **deactivates any active cluster that received no items
this run** so empty/stale topics don't linger in the UI. Returns
`{new, merged, deactivated}` stats.

### `generate_tfidf_label`
Produce a short keyword label for a cluster from its item titles via TF-IDF.

### `compute_item_links`
Populate item_links table using Qdrant ANN search.
Detects cross_cluster vs nearest_neighbour link types.
