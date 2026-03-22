# Documentation for `athena/api/migrations/add_indexes.py`

## Overview
Athena Layer 5 — Database Index Migration

Adds all indexes required by Section 7.1 of the plan document,
plus the is_active column on content_items if missing.

## Functions
### `run_migration`
Apply all indexes and schema changes.

