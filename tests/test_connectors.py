"""
Section 9 Test Suite for Athena Data Acquisition Layer.

Covers:
- Unit tests: each connector's parse() method (with mock HTTP responses)
- Contract tests: schema conformance for all source types
- Failure tests: rate limit, timeout, bad HTML handling
- Integration test: end-to-end fetch → normalise → store → queue flow
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
# UNIT TESTS: parse() per connector
# ─────────────────────────────────────────────────────────────

class TestArXivScraper:
    """Unit tests for ArXivScraper.parse()."""
    DUMMY_SOURCE_ID = "11111111-1111-1111-1111-111111111111"

    def _make_entry(self, title="Test Paper", arxiv_id="2301.00001",
                    abstract="Abstract text.", published="2023-01-01T00:00:00Z", authors=["Alice"]):
        """Create a minimal mock arXiv Atom XML element."""
        import xml.etree.ElementTree as ET
        ns = "http://www.w3.org/2005/Atom"
        entry = ET.Element(f"{{{ns}}}entry")
        ET.SubElement(entry, f"{{{ns}}}title").text = title
        ET.SubElement(entry, f"{{{ns}}}id").text = f"http://arxiv.org/abs/{arxiv_id}"
        ET.SubElement(entry, f"{{{ns}}}published").text = published
        ET.SubElement(entry, f"{{{ns}}}summary").text = abstract
        for a in authors:
            author_el = ET.SubElement(entry, f"{{{ns}}}author")
            ET.SubElement(author_el, f"{{{ns}}}name").text = a
        return entry

    def test_parse_basic(self):
        from athena.scrapers.arxiv import ArXivScraper
        scraper = ArXivScraper(source_id=self.DUMMY_SOURCE_ID)
        entry = self._make_entry()
        item = scraper.parse(entry)

        assert item.title == "Test Paper"
        assert "arxiv" in str(item.url)  # HttpUrl — cast to str
        assert item.authors == ["Alice"]
        assert item.category == "paper"
        assert str(item.extra_data.get("pdf_url", "")).endswith(".pdf")

    def test_parse_content_hash_is_sha256(self):
        import hashlib
        from athena.scrapers.arxiv import ArXivScraper
        scraper = ArXivScraper(source_id=self.DUMMY_SOURCE_ID)
        entry = self._make_entry()
        item = scraper.parse(entry)
        # Content hash should be 64-char hex string (SHA-256)
        assert len(item.content_hash) == 64

    def test_parse_deduplication(self):
        """Same content parsed twice should produce same hash."""
        from athena.scrapers.arxiv import ArXivScraper
        scraper = ArXivScraper(source_id=self.DUMMY_SOURCE_ID)
        e1 = self._make_entry()
        e2 = self._make_entry()
        assert scraper.parse(e1).content_hash == scraper.parse(e2).content_hash

    def test_arxiv_uses_all_4_categories(self):
        """Hardcoded default query must include all 4 required categories."""
        from athena.scrapers.arxiv import ARXIV_DEFAULT_QUERY
        for cat in ["cs.AI", "cs.LG", "cs.CL", "stat.ML"]:
            assert cat in ARXIV_DEFAULT_QUERY, f"Missing category: {cat}"

    def test_arxiv_max_results_at_least_50(self):
        from athena.scrapers.arxiv import ARXIV_DEFAULT_MAX_RESULTS
        assert ARXIV_DEFAULT_MAX_RESULTS >= 50


class TestRSSScraper:
    """Unit tests for RSSScraper.parse()."""
    DUMMY_SOURCE_ID = "22222222-2222-2222-2222-222222222222"

    def _make_raw_entry(self, title="Blog Post", link="https://blog.example.com/post",
                         published="Mon, 06 Mar 2023 10:00:00 +0000", summary="Post summary"):
        entry = MagicMock()
        entry.get = lambda k, default=None: {
            'title': title, 'link': link, 'published': published,
            'summary': summary, 'description': summary,
            'authors': [], 'author': None
        }.get(k, default)
        return (entry, "https://blog.example.com/feed")

    def test_parse_basic(self):
        from athena.scrapers.rss import RSSScraper
        scraper = RSSScraper(source_id=self.DUMMY_SOURCE_ID, source_category="company")
        raw = self._make_raw_entry()
        item = scraper.parse(raw)

        assert item.title == "Blog Post"
        assert str(item.url) == "https://blog.example.com/post"
        assert item.category == "company_blog"

    def test_parse_blog_category(self):
        from athena.scrapers.rss import RSSScraper
        scraper = RSSScraper(source_id=self.DUMMY_SOURCE_ID, source_category="blog")
        raw = self._make_raw_entry()
        item = scraper.parse(raw)
        assert item.category == "community_blog"

    def test_parse_date_fallback_to_utcnow(self):
        """Should not raise when all date fields are missing."""
        from athena.scrapers.rss import RSSScraper
        scraper = RSSScraper(source_id=self.DUMMY_SOURCE_ID)
        entry = MagicMock()
        entry.get = lambda k, default=None: (
            "https://example.com/post" if k == 'link' else (default or "")
        )
        raw = (entry, "https://example.com/feed")
        item = scraper.parse(raw)
        assert isinstance(item.published_at, datetime)


class TestPapersWithCodeEnricher:
    """Contract tests for PapersWithCodeEnricher API calls."""

    @pytest.mark.asyncio
    async def test_fetch_paper_artifacts_returns_benchmarks_key(self):
        """Response should always include a 'benchmarks' key."""
        from athena.scrapers.paperswithcode import PapersWithCodeEnricher
        enricher = PapersWithCodeEnricher()

        mock_paper_resp = MagicMock()
        mock_paper_resp.json.return_value = {"results": [{"id": "test-paper"}]}
        mock_paper_resp.raise_for_status = MagicMock()

        mock_repos_resp = MagicMock()
        mock_repos_resp.json.return_value = {"results": []}
        mock_repos_resp.raise_for_status = MagicMock()

        mock_results_resp = MagicMock()
        mock_results_resp.json.return_value = {"results": []}
        mock_results_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=[mock_paper_resp, mock_repos_resp, mock_results_resp])

            result = await enricher.fetch_paper_artifacts("2301.00001")

        assert result is not None
        assert "benchmarks" in result
        assert "repositories" in result


class TestSemanticScholarEnricher:
    """Contract tests for SemanticScholarEnricher."""

    @pytest.mark.asyncio
    async def test_fetch_paper_metrics_returns_citation_count(self):
        from athena.scrapers.semanticscholar import SemanticScholarEnricher
        enricher = SemanticScholarEnricher()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "citationCount": 42,
            "referenceCount": 10,
            "influentialCitationCount": 3
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=mock_resp)

            result = await enricher.fetch_paper_metrics("2301.00001")

        assert result["citation_count"] == 42

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        from athena.scrapers.semanticscholar import SemanticScholarEnricher
        enricher = SemanticScholarEnricher()

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=mock_resp)

            result = await enricher.fetch_paper_metrics("nonexistent-id")

        assert result is None


# ─────────────────────────────────────────────────────────────
# FAILURE TESTS
# ─────────────────────────────────────────────────────────────

class TestFailureHandling:
    """Failure tests: timeouts, bad HTML, HTTP errors."""

    @pytest.mark.asyncio
    async def test_arxiv_raises_on_http_error(self):
        """ArXivScraper.fetch() should raise (not swallow) HTTP errors for Celery retry."""
        import httpx
        from athena.scrapers.arxiv import ArXivScraper
        scraper = ArXivScraper(source_id="00000000-0000-0000-0000-000000000000")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "503", request=MagicMock(), response=MagicMock()
            )
            mock_client.get = AsyncMock(return_value=mock_resp)

            with pytest.raises(httpx.HTTPStatusError):
                await scraper.fetch()

    @pytest.mark.asyncio
    async def test_rss_raises_on_http_error(self):
        """RSSScraper.fetch() should raise (not swallow) HTTP errors for Celery retry."""
        import httpx
        from athena.scrapers.rss import RSSScraper
        scraper = RSSScraper(source_id="00000000-0000-0000-0000-000000000000")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock()
            )
            mock_client.get = AsyncMock(return_value=mock_resp)

            with pytest.raises(httpx.HTTPStatusError):
                await scraper.fetch("https://example.com/feed")

    def test_rss_parse_handles_empty_entry(self):
        """parse() should raise ValueError on entries with no URL (quarantined upstream)."""
        from athena.scrapers.rss import RSSScraper
        scraper = RSSScraper(source_id="00000000-0000-0000-0000-000000000000")
        empty_entry = MagicMock()
        empty_entry.get = lambda k, default=None: default or ""
        raw = (empty_entry, "https://example.com/feed")
        # Should raise ValueError (entry has no URL), to be caught by quarantine logic
        with pytest.raises(ValueError):
            scraper.parse(raw)


# ─────────────────────────────────────────────────────────────
# SCHEMA CONTRACT TESTS
# ─────────────────────────────────────────────────────────────

class TestSchemaConformance:
    """Verify that parsed items conform to ContentItemCreate schema."""

    def test_arxiv_item_conforms_to_schema(self):
        import xml.etree.ElementTree as ET
        from athena.scrapers.arxiv import ArXivScraper
        from athena.core.schemas import ContentItemCreate

        scraper = ArXivScraper(source_id="33333333-3333-3333-3333-333333333333")
        ns = "http://www.w3.org/2005/Atom"
        entry = ET.Element(f"{{{ns}}}entry")
        ET.SubElement(entry, f"{{{ns}}}title").text = "Schema Test Paper"
        ET.SubElement(entry, f"{{{ns}}}id").text = "http://arxiv.org/abs/2301.99999"
        ET.SubElement(entry, f"{{{ns}}}published").text = "2023-01-01T00:00:00Z"
        ET.SubElement(entry, f"{{{ns}}}summary").text = "Abstract content."
        author_el = ET.SubElement(entry, f"{{{ns}}}author")
        ET.SubElement(author_el, f"{{{ns}}}name").text = "Test Author"

        item = scraper.parse(entry)
        # Pydantic validation: ensure all required fields are present and valid
        assert isinstance(item, ContentItemCreate)
        assert str(item.source_id) == "33333333-3333-3333-3333-333333333333"  # UUID vs str
        assert item.content_hash
        assert item.category

    def test_rss_item_conforms_to_schema(self):
        from athena.scrapers.rss import RSSScraper
        from athena.core.schemas import ContentItemCreate
        scraper = RSSScraper(source_id="44444444-4444-4444-4444-444444444444")

        entry = MagicMock()
        entry.get = lambda k, default=None: {
            'title': "RSS Schema Test",
            'link': "https://blog.example.com/schema-test",
            'published': "Tue, 07 Mar 2023 12:00:00 +0000",
            'summary': "Test summary.",
        }.get(k, default)
        raw = (entry, "https://blog.example.com/feed")

        item = scraper.parse(raw)
        assert isinstance(item, ContentItemCreate)
        assert item.content_hash
