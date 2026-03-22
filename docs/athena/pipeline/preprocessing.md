# Documentation for `athena/pipeline/preprocessing.py`

## Overview
No module level docstring provided.

## Functions
### `preprocess`
Athena Layer 2 Preprocessing:
1. Strip HTML tags
2. Remove navigation, footer, sidebar elements
3. Normalize whitespace
4. Normalize URLs (domain only)
5. Normalize Unicode (NFKC)
6. Structured prefixing
7. Truncate to token limit

