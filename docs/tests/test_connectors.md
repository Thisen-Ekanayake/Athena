# Documentation for `tests/test_connectors.py`

## Overview
Section 9 Test Suite for Athena Data Acquisition Layer.

Covers:
- Unit tests: each connector's parse() method (with mock HTTP responses)
- Contract tests: schema conformance for all source types
- Failure tests: rate limit, timeout, bad HTML handling
- Integration test: end-to-end fetch → normalise → store → queue flow

## Classes
### `TestArXivScraper`
Unit tests for ArXivScraper.parse().

### `TestRSSScraper`
Unit tests for RSSScraper.parse().

### `TestPapersWithCodeEnricher`
Contract tests for PapersWithCodeEnricher API calls.

### `TestSemanticScholarEnricher`
Contract tests for SemanticScholarEnricher.

### `TestFailureHandling`
Failure tests: timeouts, bad HTML, HTTP errors.

### `TestSchemaConformance`
Verify that parsed items conform to ContentItemCreate schema.

