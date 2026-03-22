# Documentation for `athena/pipeline/tasks.py`

## Overview
No module level docstring provided.

## Functions
### `_push_to_dlq`
Push a permanently failed task to the dead-letter queue in Redis.

### `setup_periodic_tasks`
No docstring provided.

### `generate_all_trending_briefs`
Trigger daily trending brief generation for all categories.

### `enqueue_tier2_summaries`
Phase 3: Periodic background job to enqueue Tier 2 items for summarisation.

### `crawl_all_sources`
No docstring provided.

### `crawl_source`
No docstring provided.

### `enrich_arxiv_paper`
No docstring provided.

### `_enrich_paper_async`
No docstring provided.

### `_get_scraper`
Factory: return the right scraper for this source type and URL.

### `_crawl_source_async`
No docstring provided.

### `stage_content_item`
Phase 5: Write full text to staging directory, update ContentItem.full_text_path,
and push the item UUID onto the Redis embedding queue.

### `_preprocess_text`
Strip HTML tags, normalize whitespace, and truncate to token limit.

