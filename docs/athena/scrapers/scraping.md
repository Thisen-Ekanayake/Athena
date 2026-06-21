# Documentation for `athena/scrapers/scraping.py`

## Overview
No module level docstring provided.

## Classes
### `PlaywrightScraper`
Scraper that fetches RSS feeds to find URLs, and then uses a headless browser
(Playwright) and Newspaper3k to bypass paywalls/JS blocks and extract the full
clean body text of the articles.

When the source URL is an HTML page rather than a feed, `fetch()` falls back to
`_discover_feed()` — feed autodiscovery via `<link rel="alternate">` and common
feed paths (`/rss/`, `/feed/`, `/atom.xml`, …) — and returns early (before
launching a browser) when no feed can be found, so feedless sources degrade
gracefully instead of crashing.

#### Methods
- `_discover_feed(url)` — resolve an RSS/Atom feed from an HTML page URL; returns
  the first candidate that yields entries, or None.
- `fetch(url)` — discover/parse the feed, then fetch each article's full HTML.
- `parse(raw)` — extract clean body text with Newspaper3k into a ContentItem.
