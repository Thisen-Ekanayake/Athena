# Documentation for `scripts/backfill_embeddings.py`

## Overview
Backfill embeddings for items that were never embedded.

Items get embedded only when crawled live (`stage_content_item` → embedding
queue). Items ingested before the embedding pipeline was healthy — or whose
staging files were lost (e.g. `/var/lib/athena/staging` wiped) — are left with
`embedded_at = NULL` and a `full_text_path` pointing at a missing file, so the
embedding worker skips them forever.

This script re-stages every such item from its title + abstract and pushes it
onto the embedding queue. Idempotent: only touches `embedded_at IS NULL` rows.

## Usage
```bash
python -m scripts.backfill_embeddings           # re-stage + enqueue only
python -m scripts.backfill_embeddings --drain    # also embed now (uses OpenAI)
```

## Functions
### `_staging_dir`
Return STAGING_DIR, falling back to /tmp when it isn't writable (dev machines).

### `backfill`
Re-stage and enqueue every item with `embedded_at IS NULL`. Returns the count.

### `drain`
Process the embedding queue to completion (calls OpenAI; costs credits).
