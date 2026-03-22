# Documentation for `athena/scrapers/substack.py`

## Overview
Generic Substack RSS Harvester.
Substack blogs publish RSS feeds at: https://<blog>.substack.com/feed
This scraper accepts any Substack URL and constructs the RSS feed URL automatically.

## Classes
### `SubstackScraper`
Generic Substack RSS harvester.
`url` should be the base Substack URL (e.g. https://gradientflow.substack.com).
Feed URL is auto-constructed as <base>/feed.

## Functions
### `detect_substack_feed`
Given a Substack URL (e.g. https://gradientflow.substack.com or
https://gradientflow.substack.com/p/some-post), return the RSS feed URL.

