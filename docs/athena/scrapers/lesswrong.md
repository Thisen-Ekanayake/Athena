# Documentation for `athena/scrapers/lesswrong.py`

## Overview
LessWrong and AI Alignment Forum API scrapers.
Both platforms share the same GraphQL API endpoint format.
No headless scraping required — they provide a public GraphQL API.

## Classes
### `LessWrongScraper`
Fetches posts from LessWrong via their public GraphQL API.

### `AIAlignmentForumScraper`
Fetches posts from the AI Alignment Forum.
Identical GraphQL API to LessWrong — only the endpoint differs.

