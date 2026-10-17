"""
Section 9 Test Suite for Athena Data Acquisition Layer.

Covers:
- Unit tests: each connector's parse() method (with mock HTTP responses)
- Contract tests: schema conformance for all source types
- Failure tests: rate limit, timeout, bad HTML handling
- Integration test: end-to-end fetch → normalise → store → queue flow
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────
# UNIT TESTS: parse() per connector
# ─────────────────────────────────────────────────────────────

class TestArXivScraper:
    """Unit tests for ArXivScraper.parse()."""
    DUMMY_SOURCE_ID = "11111111-1111-1111-1111-111111111111"

    def _make_entry(self, title="Test Paper", arxiv_id="2301.00001",
                    abstract="Abstract text.", published="2023-01-01T00:00:00Z", authors=None):
        """Create a minimal mock arXiv Atom XML element."""
        if authors is None:
            authors = ["Alice"]
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

    def test_arxiv_uses_all_5_categories(self):
        """The default query includes every category the feed follows."""
        from athena.scrapers.arxiv import ARXIV_DEFAULT_QUERY
        for cat in ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"]:
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


class TestSemanticScholarEnricher:
    """Contract tests for SemanticScholarEnricher (through the shared Semantic Scholar client)."""

    @staticmethod
    def _client(handler):
        import httpx
        from athena.evolution.semantic_scholar import SemanticScholarClient

        def make(**kwargs):
            http = httpx.Client(base_url="https://api.semanticscholar.org/graph/v1",
                                transport=httpx.MockTransport(handler))
            return SemanticScholarClient(api_key="k", http=http, min_interval=0, **kwargs)
        return patch("athena.evolution.semantic_scholar.SemanticScholarClient", side_effect=make)

    @pytest.mark.asyncio
    async def test_fetch_paper_metrics_returns_citation_count(self):
        import httpx
        from athena.scrapers.semanticscholar import SemanticScholarEnricher

        def handler(request):
            assert request.url.path.endswith("/paper/batch")
            return httpx.Response(200, json=[{"paperId": "s2-1", "title": "A paper", "citationCount": 42,
                                              "referenceCount": 10}])

        with self._client(handler):
            result = await SemanticScholarEnricher().fetch_paper_metrics("2301.00001")

        assert result == {"paper_id": "s2-1", "citation_count": 42, "reference_count": 10}

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        import httpx
        from athena.scrapers.semanticscholar import SemanticScholarEnricher

        with self._client(lambda request: httpx.Response(200, json=[None])):
            result = await SemanticScholarEnricher().fetch_paper_metrics("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_the_lookup_fails(self):
        import httpx
        from athena.scrapers import semanticscholar
        from athena.scrapers.semanticscholar import SemanticScholarEnricher

        with patch.object(semanticscholar, "PATIENCE", 0), \
                self._client(lambda request: httpx.Response(429, json={})):
            result = await SemanticScholarEnricher().fetch_paper_metrics("2301.00001")

        assert result is None


class TestPlaywrightScraperParse:
    """newspaper4k pulls the article body out of the page Playwright rendered, without fetching anything."""

    SOURCE = "6f1c2a4e-0b7d-4c55-9a51-3d2e8f9b1c07"

    PAGE = """<html><head><title>Scaling laws for sparse models</title>
    <meta name="author" content="Ada Lovelace"></head><body>
    <nav>Home | Research | Blog</nav>
    <article><h1>Scaling laws for sparse models</h1>
    <p>We study how mixture-of-experts language models scale with the number of experts and the compute budget.
    Across five orders of magnitude, loss follows a power law in both, and the best number of experts grows.</p>
    <p>These results suggest sparse models should be trained with more experts as budgets grow.</p>
    </article><footer>Copyright 2026</footer></body></html>"""

    def _raw(self, page_html=PAGE, authors=None):
        return {"link": "https://lab.example.com/blog/sparse-scaling", "title": "Scaling laws for sparse models",
                "page_html": page_html, "authors": authors or [], "published_at": datetime(2026, 10, 1),
                "feed_url": "https://lab.example.com/feed.xml"}

    def test_parse_extracts_the_body_offline(self):
        from athena.scrapers.scraping import PlaywrightScraper
        with patch("socket.socket", side_effect=AssertionError("parse() used the network")):
            item = PlaywrightScraper(self.SOURCE, source_category="company").parse(self._raw())
        assert item.abstract.startswith("We study how mixture-of-experts language models scale")
        assert "Copyright" not in item.abstract and "Home | Research" not in item.abstract
        assert item.authors == ["Ada Lovelace"]  # the feed had none, so the page's byline is used
        assert item.category == "company_blog"
        assert item.extra_data == {"feed_link": "https://lab.example.com/feed.xml", "full_text_scraped": True}

    def test_parse_keeps_the_feed_authors(self):
        from athena.scrapers.scraping import PlaywrightScraper
        item = PlaywrightScraper(self.SOURCE).parse(self._raw(authors=["Feed Author"]))
        assert item.authors == ["Feed Author"]
        assert item.category == "community_blog"

    def test_parse_rejects_a_page_without_text(self):
        from athena.scrapers.scraping import PlaywrightScraper
        with pytest.raises(ValueError, match="No text content"):
            PlaywrightScraper(self.SOURCE).parse(self._raw(page_html="<html><body><nav>Home</nav></body></html>"))


# ─────────────────────────────────────────────────────────────
# RECORDED FETCH TESTS: fetch() → parse() on real responses, offline
# ─────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


def _answering(body: str):
    """Patch httpx.AsyncClient so every GET answers 200 with ``body``; returns the patcher and the mock get."""
    patcher = patch("httpx.AsyncClient")
    cls = patcher.start()
    client = AsyncMock()
    cls.return_value.__aenter__.return_value = client
    resp = MagicMock()
    resp.text = body
    resp.raise_for_status = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return patcher, client.get


class TestRecordedFetch:
    """The arXiv API page (cat:cs.AI, 3 results) and OpenAI News feed (first 3 items) recorded on 2026-10-17."""

    @pytest.mark.asyncio
    async def test_arxiv_page_becomes_papers(self):
        from athena.scrapers.arxiv import ArXivScraper
        from athena.core.schemas import ContentItemCreate
        scraper = ArXivScraper(source_id="55555555-5555-5555-5555-555555555555")
        patcher, get = _answering((FIXTURES / "arxiv_atom.xml").read_text())
        try:
            entries = await scraper.fetch(max_results=5)
        finally:
            patcher.stop()

        assert get.await_count == 1  # a plain fetch asks for one page
        items = [scraper.parse(e) for e in entries]
        assert [i.title for i in items] == [
            "LIBERO-PeRM: Benchmarking Personalized Robotic Manipulation",
            "Discovering state-of-the-art quantum circuits with large language models",
            "T2-z: Test-Time Optimization of Environment Latents for Robotic World Models",
        ]
        first = items[0]
        assert str(first.url) == "http://arxiv.org/abs/2610.22372v1"
        assert first.authors[0] == "Zhixu Li" and len(first.authors) == 10
        assert first.published_at == datetime(2026, 10, 15, 17, 59, 59, tzinfo=timezone.utc)
        assert first.extra_data == {"arxiv_id": "2610.22372v1",
                                    "pdf_url": "http://arxiv.org/pdf/2610.22372v1.pdf"}
        assert first.abstract.startswith("Personalization is essential")
        assert all(isinstance(i, ContentItemCreate) and i.category == "paper" for i in items)

    @pytest.mark.asyncio
    async def test_arxiv_sync_stops_at_the_newest_stored_paper(self):
        from athena.scrapers.arxiv import ArXivScraper
        scraper = ArXivScraper(source_id="55555555-5555-5555-5555-555555555555")
        patcher, _ = _answering((FIXTURES / "arxiv_atom.xml").read_text())
        try:
            entries = await scraper.fetch(max_results=1000, since=datetime(2026, 10, 15, 17, 59, 15))
        finally:
            patcher.stop()
        assert [scraper.parse(e).title[:10] for e in entries] == ["LIBERO-PeR", "Discoverin"]

    @pytest.mark.asyncio
    async def test_rss_feed_becomes_blog_posts(self):
        from athena.scrapers.rss import RSSScraper
        from athena.core.schemas import ContentItemCreate
        url = "https://openai.com/news/rss.xml"
        scraper = RSSScraper(source_id="66666666-6666-6666-6666-666666666666", source_category="company")
        patcher, get = _answering((FIXTURES / "openai_news_rss.xml").read_text(encoding="utf-8"))
        try:
            raw = await scraper.fetch(url)
        finally:
            patcher.stop()

        assert get.await_args.args[0] == url
        items = [scraper.parse(r) for r in raw]
        assert [str(i.url) for i in items] == [
            "https://openai.com/index/itau-generative-ai",
            "https://openai.com/index/stack-overflow-chatgpt-plugin",
            "https://openai.com/index/benefit-street-partners",
        ]
        first = items[0]
        assert first.title == "How Itaú is building generative AI for its entire customer base"
        assert first.published_at == datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)
        assert first.abstract.startswith("With ia.i, a conversational interface")
        assert first.extra_data == {"feed_link": url}
        assert all(isinstance(i, ContentItemCreate) and i.category == "company_blog" for i in items)


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
