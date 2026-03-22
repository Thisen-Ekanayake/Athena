# Documentation for `athena/pipeline/clustering.py`

## Overview
No module level docstring provided.

## Functions
### `run_clustering`
Main clustering job:
1. Fetch all embeddings from Qdrant
2. Reduce dimensionality with UMAP
3. Group with HDBSCAN
4. Label with TF-IDF
5. Handle stability/re-assignment
6. Persist results to DB

### `process_clusters`
No docstring provided.

### `generate_tfidf_label`
No docstring provided.

### `compute_item_links`
Populate item_links table using Qdrant ANN search.
Detects cross_cluster vs nearest_neighbour link types.

