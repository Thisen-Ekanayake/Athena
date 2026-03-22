# Documentation for `athena/scrapers/scraping.py`

## Overview
No module level docstring provided.

## Classes
### `PlaywrightScraper`
Scraper that fetches RSS feeds to find URLs, and then uses a headless browser
(Playwright) and Newspaper3k to bypass paywalls/JS blocks and extract the full
clean body text of the articles.

