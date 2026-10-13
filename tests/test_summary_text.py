"""The text a summary is written from: staged text, the fetched article when that is thin, or nothing."""
from types import SimpleNamespace
from unittest.mock import patch

from athena.core.qa_fetcher import FetchResult
from athena.pipeline import summarisation_tasks as st

ITEM = SimpleNamespace(id="i1", url="https://example.com/post", title="Introducing Falcon ASR", abstract=None)
FETCH = "athena.core.qa_fetcher.fetch_article_content"


def _fetched(text, partial=False):
    """A stand-in for the async fetcher (patch makes it an AsyncMock, which awaits an async side effect)."""
    async def fetch(item):
        return FetchResult(text=text, method="http", word_count=len(text.split()), partial=partial)
    return fetch


def test_enough_staged_text_is_used_without_fetching():
    staged = "word " * 200
    with patch(FETCH, side_effect=AssertionError("should not fetch")):
        assert st._text_to_summarise(ITEM, staged) == staged


def test_a_thin_staged_text_is_replaced_by_the_fetched_article():
    article = "The model transcribes speech. " * 40
    with patch(FETCH, side_effect=_fetched(article)):
        assert st._text_to_summarise(ITEM, "Introducing Falcon ASR") == article


def test_nothing_to_summarise_when_only_metadata_is_found():
    with patch(FETCH, side_effect=_fetched("Title: Introducing Falcon ASR " * 30, partial=True)):
        assert st._text_to_summarise(ITEM, "Introducing Falcon ASR") is None
    with patch(FETCH, side_effect=RuntimeError("offline")):
        assert st._text_to_summarise(ITEM, "") is None


def test_long_articles_are_cut_to_fit_the_local_model():
    text = st._text_to_summarise(ITEM, "word " * (st.MAX_SUMMARY_WORDS + 500))
    assert len(text.split()) == st.MAX_SUMMARY_WORDS


def test_the_fetcher_reads_the_items_own_staged_file_only_when_it_has_content(tmp_path):
    import asyncio
    from athena.core import qa_fetcher

    staged = tmp_path / "item.txt"
    item = SimpleNamespace(id="i2", url="https://example.com/post", title="T", abstract=None,
                           full_text_path=str(staged))
    page = qa_fetcher.FetchResult(text="page " * 300, method="http", word_count=300)

    async def direct(url):
        return page

    staged.write_text("Introducing Falcon ASR")
    with patch.object(qa_fetcher, "try_direct_fetch", side_effect=direct):
        assert asyncio.run(qa_fetcher.fetch_article_content(item)).method == "http"
    staged.write_text("word " * 300)
    with patch.object(qa_fetcher, "try_direct_fetch", side_effect=AssertionError("should not fetch")):
        assert asyncio.run(qa_fetcher.fetch_article_content(item)).method == "staged"
