# Documentation for `athena/core/models.py`

## Overview
No module level docstring provided.

## Classes
### `SummaryStatus`
No docstring provided.

### `JobType`
No docstring provided.

### `SourceType`
No docstring provided.

### `SourceCategory`
No docstring provided.

### `ContentCategory`
No docstring provided.

### `Source`
No docstring provided.

### `ContentItem`
No docstring provided.

### `FetchLog`
No docstring provided.

### `QuarantineItem`
Holds raw items that failed Pydantic schema validation for later inspection.

### `Cluster`
No docstring provided.

### `ItemLink`
No docstring provided.

### `ContentScore`
Per-item sub-score breakdown for scoring transparency.

### `ScoringConfig`
Versioned weight profiles per content category.

### `MetricSnapshot`
Daily snapshot of citation_count + engagement per item for velocity computation.

### `PromptVersion`
Versioning for LLM prompts used in summarisation.

### `SummaryUsageLog`
Audit log for OpenAI LLM token usage and cost.

### `TrendingBrief`
Daily generated trend digest per category.

### `QAFetchCache`
Caches fetch status and metadata for Q&A features.

### `QAUsageLog`
Audit log for Q&A feature token usage and session history.

### `ClusterRunLog`
Audit log for clustering pipeline runs.

### `ReferenceEmbedding`
Stores positive/negative reference embeddings for semantic scoring.

### `ScoreAuditLog`
Audit log for significant score changes (> 0.1 delta).

