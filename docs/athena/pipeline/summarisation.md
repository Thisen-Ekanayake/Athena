# Documentation for `athena/pipeline/summarisation.py`

## Overview
Athena Layer 4 — Summarisation Core Logic

Contains utilities for Redis-based budget tracking, Pydantic validation of OpenAI
responses, and core logic for formatting prompts and generating summaries.

## Classes
### `SummaryOutput`
No docstring provided.

## Functions
### `parse_and_validate`
Parse raw LLM response into a validated SummaryOutput object.

### `today_date`
Returns YYYY-MM-DD in UTC for budget tracking.

### `check_budget_before_call`
Check if we have exceeded the daily summary budget.
Tier 1 (urgent/trending) is exempt from the 80% threshold.
Tier 2/3 pauses at 80% of daily budget to reserve capacity for urgent items.

### `log_usage_and_update_spend`
Logs usage to the DB and increments daily spend in Redis.

### `get_active_prompt_version`
Fetch the currently active prompt version for a given job type.

