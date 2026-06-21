# Documentation for `athena/database/user_sources.py`

## Overview
User-Managed Source Utilities (Section 8 of the acquisition plan).

Provides:
- detect_source_type(url) -> SourceType
- preview_source(url, name) -> dict (frontend-shaped preview, no DB write)
- add_user_source(url, name) -> dict (saves with added_by='user', queues first crawl)

## Functions
### `detect_source_type`
Auto-detect the source type given any URL.
Logic per Section 8.2 of the acquisition plan:
1. Try fetching as RSS/Atom
2. Check known API patterns
3. Default to SCRAPE (Playwright)

### `_derive_name`
Best-effort human-friendly source name from a URL (hostname, `www.` stripped).

### `preview_source`
Test-fetch a URL and return a preview without writing to the DB, shaped for the
frontend: `{source_type, source_name, sample_items: [{title, url, published_at,
summary}]}`. RSS feeds return real sample items; API/SCRAPE sources return an
empty sample list (still addable). A hard failure (URL unreachable) returns an
`error` key so the caller can surface a 400.

### `add_user_source`
Add a user-managed source:
1. Auto-detect type
2. Upsert into sources table with added_by='user'
3. Queue the first crawl immediately (best-effort — a broker outage no longer
   fails the add; the periodic crawl picks it up regardless)
