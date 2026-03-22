# Documentation for `athena/database/user_sources.py`

## Overview
User-Managed Source Utilities (Section 8 of the acquisition plan).

Provides:
- detect_source_type(url) -> SourceType
- add_user_source(url, name) -> Source (test-fetches, confirms, saves, queues first crawl)

## Functions
### `detect_source_type`
Auto-detect the source type given any URL.
Logic per Section 8.2 of the acquisition plan:
1. Try fetching as RSS/Atom
2. Check known API patterns
3. Default to SCRAPE (Playwright)

### `preview_source`
Perform a test fetch and return a preview of what data would be retrieved.
Used to let users confirm before a source is added.

### `add_user_source`
Add a user-managed source:
1. Auto-detect type
2. Preview fetch
3. Upsert into sources table with added_by='user'
4. Queue the first crawl immediately

