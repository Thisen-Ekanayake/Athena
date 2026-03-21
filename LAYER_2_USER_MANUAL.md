# Athena Layer 2: Embedding & Clustering - User Manual

This manual covers the Embedding and Clustering layer (Layer 2) of the Athena system. This layer is responsible for converting unstructured text into semantic vectors, grouping them into topics, and finding related articles.

## 1. Overview

Layer 2 consumes content staged by Layer 1 (Data Acquisition). It follows a multi-step pipeline:
1. **Preprocessing**: Cleans and structures raw text.
2. **Embedding**: Generates 1536-dimensional vectors using OpenAI.
3. **Clustering**: Groups vectors into topics using UMAP and HDBSCAN.
4. **Linking**: Finds the top-5 most similar items for every article.

## 2. Prerequisites

- **OpenAI API Key**: Must be set in the `.env` file as `OPENAI_API_KEY`.
- **Qdrant**: Must be running (via `docker-compose up -d`).
- **Python Dependencies**: Ensure you have installed the Layer 2 requirements:
  ```bash
  pip install qdrant-client umap-learn hdbscan scikit-learn beautifulsoup4 tiktoken openai
  ```

## 3. Core Components

### 3.1 Preprocessing (`athena/pipeline/preprocessing.py`)
Automatically cleans raw text before embedding:
- Strips HTML and removes non-content elements (nav, footer, sidebar).
- Normalizes URLs and whitespace.
- Truncates content to 8,000 tokens (tiktoken) to fit model limits.
- Adds structure: `Title: ... | Authors: ... | Abstract: ... | Body: ...`.

### 3.2 Embedding Worker (`athena/pipeline/embedding_worker.py`)
A Celery task that pulls items from `athena:embedding_queue`:
- Processes items in batches of 20.
- Uses `text-embedding-3-small`.
- Stores vectors in Qdrant with metadata (title, url, source).
- Updates PostgreSQL with `embedding_id` and `embedded_at`.

### 3.3 Clustering Engine (`athena/pipeline/clustering.py`)
A scheduled job that runs across all embedded items:
- **Dimensionality Reduction**: Reduces 1536-d vectors to 50-d using UMAP.
- **Clustering**: Groups items using HDBSCAN.
- **Labeling**: Generates human-readable labels (e.g., 'lora finetuning llm') using TF-IDF.
- **Stability**: Reuses existing Cluster IDs if the new centroid is >85% similar to the old one.

## 4. How to Run

### 4.1 Start the Worker
The embedding and clustering tasks are executed by the Celery worker. Start it with:
```bash
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

### 4.2 Automation & Scheduling
Tasks are automatically scheduled in `athena/pipeline/tasks.py`:
- **Embedding**: Runs every **1 minute** (checks for new items in Redis).
- **Clustering**: Runs every **6 hours**.
- **Item Linking**: Runs every **6 hours** (immediately after clustering).

### 4.3 Manual Trigger (Optional)
You can trigger these tasks manually via a Python shell:
```python
from athena.pipeline.embedding_worker import process_embedding_queue
from athena.pipeline.clustering import run_clustering, compute_item_links

# Process any pending embeddings
process_embedding_queue.delay()

# Run a full clustering pass
run_clustering.delay()

# Re-compute item links
compute_item_links.delay()
```

## 5. Verification

### 5.1 Check Database
Verify that items are being embedded and clusters are being formed:
```sql
-- Check embedded count
SELECT count(*) FROM content_items WHERE embedding_id IS NOT NULL;

-- View clusters
SELECT * FROM clusters WHERE is_active = True ORDER BY created_at DESC;

-- View item links
SELECT * FROM item_links LIMIT 10;
```

### 5.2 Check Qdrant
Access the Qdrant Dashboard (if enabled) or use the API:
```bash
curl http://localhost:6333/collections/athena_content
```

## 6. Troubleshooting

- **Empty Clusters**: Ensure you have at least 5-10 embedded items. HDBSCAN requires a minimum cluster size (default: 5).
- **OpenAI Errors**: Check your API key and balance. Rate limits are handled by Celery retries.
- **Missing Vectors**: Ensure the Celery worker is running and that items were successfully staged to `/tmp/athena/staging/`.
