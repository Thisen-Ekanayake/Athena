# Documentation for `athena/pipeline/summarisation_tasks.py`

## Overview
No module level docstring provided.

## Functions
### `_get_openai_client`
No docstring provided.

### `build_item_summary_prompt`
No docstring provided.

### `_does_item_need_resummary`
No docstring provided.

### `summarise_item_worker`
Tiered summarisation worker. Can be driven by any tier queue.
Fetches the item, checks budget, loads text, generates summary.
tier=1: urgent (exempt from 80% budget cap)
tier=2: standard (pauses at 80% budget)
tier=3: lazy (on-demand only, pauses at 80% budget)

### `summarise_on_demand_sync`
Synchronous on-demand summary for Tier 3 items, triggered by API.

### `label_cluster_worker`
Generate label and description for a cluster based on top 5 items.

### `generate_trending_brief_worker`
Generate daily trending brief for a specific category based on top trending items.

