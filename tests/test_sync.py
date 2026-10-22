"""A sync's progress and log (sync_status), its routes, the crawl task's outcomes and the scraper fixes."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from athena.api.auth import active_user, current_user
from athena.api.deps import get_redis
from athena.api.main import app
from athena.core.models import User
from athena.pipeline import sync_status
from tests.fakes import FakeRedis

SOURCES = [("a", "ArXiv", 20.0), ("b", "Blog", 5.0), ("c", "News", None)]


@pytest.fixture
def r():
    return FakeRedis()


def entries(r, sync_id):
    return {s["id"]: s for s in sync_status.status(r)["sources"]} if sync_id else {}


# ── progress and state ──────────────────────────────────────────────

def test_a_sync_runs_once_and_the_last_source_closes_it(r):
    sync_id = sync_status.start(r, SOURCES, "manual")
    assert sync_id and sync_status.running(r) == sync_id
    assert sync_status.start(r, SOURCES, "scheduled") is None  # one at a time

    sync_status.source_started(r, sync_id, "a")
    sync_status.source_finished(r, sync_id, "a", "done", new=4)
    sync_status.source_finished(r, sync_id, "b", "empty")
    status = sync_status.status(r)
    assert status["state"] == "running" and status["completed"] == 2 and status["new_items"] == 4

    sync_status.source_finished(r, sync_id, "c", "done", new=1)
    status = sync_status.status(r)
    assert status["state"] == "partial"  # a source listed nothing
    assert status["percent"] == 100 and status["eta_seconds"] == 0 and status["new_items"] == 5
    assert sync_status.running(r) is None
    assert sync_status.start(r, SOURCES, "manual")  # the next one may start


def test_a_finished_source_is_counted_once(r):
    sync_id = sync_status.start(r, SOURCES, "manual")
    sync_status.source_finished(r, sync_id, "a", "done", new=2)
    sync_status.source_finished(r, sync_id, "a", "error", error="late duplicate")
    status = sync_status.status(r)
    assert status["completed"] == 1 and status["errors"] == 0 and entries(r, sync_id)["a"]["state"] == "done"


@pytest.mark.parametrize("outcomes, state", [
    (["done", "done", "done"], "done"),
    (["done", "error", "done"], "partial"),
    (["error", "error", "error"], "error"),
])
def test_the_result_says_how_it_went(r, outcomes, state):
    sync_id = sync_status.start(r, SOURCES, "manual")
    for (source_id, _, _), outcome in zip(SOURCES, outcomes):
        sync_status.source_finished(r, sync_id, source_id, outcome)
    assert sync_status.status(r)["state"] == state


def test_progress_weights_sources_by_their_usual_time():
    sources = [{"state": "done", "expected": 30.0}, {"state": "queued", "expected": 10.0}]
    pct, eta = sync_status.progress(sources, started_at=0, now=30)
    assert pct == 75.0 and eta == pytest.approx(10.0)


def test_a_running_source_moves_the_bar_but_not_past_most_of_its_share():
    sources = [{"state": "running", "expected": 10.0, "started_at": 0}, {"state": "queued", "expected": 10.0}]
    assert sync_status.progress(sources, 0, now=4)[0] == pytest.approx(20.0)
    assert sync_status.progress(sources, 0, now=60)[0] == pytest.approx(45.0)  # 90% of its half


def test_a_source_past_its_usual_time_gives_no_short_estimate():
    sources = [{"state": "done", "expected": 30.0}, {"state": "running", "expected": 2.0, "started_at": 0}]
    pct, eta = sync_status.progress(sources, started_at=0, now=40)
    assert pct > 95 and eta is None  # not "1 s left" while a scrape that usually takes 2 s runs on


def test_no_estimate_until_there_is_some_pace_and_retries_set_a_floor():
    assert sync_status.progress([{"state": "queued", "expected": 10.0}], 0, now=1) == (0.0, None)
    sources = [{"state": "done", "expected": 10.0}, {"state": "retrying", "expected": 10.0, "retry_at": 130}]
    pct, eta = sync_status.progress(sources, 0, now=100)
    assert pct == 50.0 and eta == pytest.approx(100.0)  # waits 30 s, then ~10 s; the pace alone says 100


def test_a_sync_nobody_reports_on_is_stalled_and_an_idle_worker_shows(r):
    sync_id = sync_status.start(r, SOURCES, "manual")
    meta = r.store[f"athena:sync:{sync_id}"]
    meta["started_at"] = time.time() - 60
    assert sync_status.status(r)["waiting_for_worker"] is True
    r.delete(sync_status.RUNNING)  # expired: no source reported for RUNNING_TTL
    status = sync_status.status(r)
    assert status["state"] == "stalled" and status["eta_seconds"] is None


def test_the_log_is_kept_in_order_and_read_from_a_point(r):
    sync_id = sync_status.start(r, SOURCES, "manual")
    for i in range(3):
        sync_status.log(r, sync_id, f"line {i}")
    assert "log" not in sync_status.status(r)
    log = sync_status.status(r, with_log=True, log_after=1)["log"]
    assert [x["line"] for x in log] == ["line 1", "line 2"] and log[-1]["seq"] == 3


def test_nothing_synced_yet_is_idle(r):
    assert sync_status.status(r) == {"state": "idle"}


# ── routes ──────────────────────────────────────────────────────────

@pytest.fixture
def api(r):
    app.dependency_overrides[get_redis] = lambda: r
    sources = [SimpleNamespace(id=uuid4(), name=n) for n in ("ArXiv", "Blog")]
    with patch("athena.api.routers.sync.get_active_sources", return_value=sources), \
            patch("athena.api.routers.sync.fetch_durations", return_value={}), \
            patch("athena.api.routers.sync.celery_app.send_task") as send:
        yield TestClient(app), send
    app.dependency_overrides.pop(get_redis, None)


def test_starting_a_sync_shows_it_at_once_and_a_second_waits(api):
    c, send = api
    first = c.post("/api/v1/sync")
    assert first.status_code == 200 and first.json()["state"] == "running" and first.json()["total"] == 2
    assert send.call_args.kwargs["kwargs"] == {"sync_id": first.json()["id"]}
    assert c.post("/api/v1/sync").status_code == 409
    assert send.call_count == 1


def test_everyone_sees_progress_but_only_admins_the_log(api, r):
    c, _ = api
    sync_id = c.post("/api/v1/sync").json()["id"]
    sync_status.log(r, sync_id, "12:00:00 | INFO | Crawling source: Blog (https://example.com)")
    assert "log" not in c.get("/api/v1/sync/status").json()  # the sidebar's polls leave it out
    assert len(c.get("/api/v1/sync/status", params={"log": True}).json()["log"]) == 1
    reader = User(id=uuid4(), email="bo@example.com", display_name="Bo", password_hash="-", role="user",
                  is_active=True)
    app.dependency_overrides[current_user] = lambda: reader
    app.dependency_overrides[active_user] = lambda: reader
    body = c.get("/api/v1/sync/status", params={"log": True}).json()
    assert body["state"] == "running" and "log" not in body
    assert c.post("/api/v1/sync").status_code == 403


# ── the crawl task ──────────────────────────────────────────────────

class Retried(Exception):
    pass


@pytest.fixture
def task(r):
    from athena.pipeline import crawl
    sync_id = sync_status.start(r, SOURCES, "manual")
    with patch.object(crawl, "get_redis", return_value=r), patch.object(crawl, "_push_to_dlq") as dlq, \
            patch.object(crawl.crawl_source, "retry", side_effect=Retried):
        yield crawl, sync_id, dlq


def run(tasks, sync_id, retries=0):
    tasks.crawl_source.push_request(retries=retries)
    try:
        tasks.crawl_source.run("a", sync_id)
    finally:
        tasks.crawl_source.pop_request()


def test_a_source_that_lists_nothing_is_empty_not_done(task, r):
    tasks, sync_id, _ = task
    with patch.object(tasks, "_crawl_source_async", AsyncMock(return_value=(0, 0))):
        run(tasks, sync_id)
    assert entries(r, sync_id)["a"]["state"] == "empty"
    with patch.object(tasks, "_crawl_source_async", AsyncMock(return_value=(10, 3))):
        tasks.crawl_source.run("b", sync_id)
    assert entries(r, sync_id)["b"]["state"] == "done" and sync_status.status(r)["new_items"] == 3


def test_a_failure_is_retried_soon_then_given_up_with_its_error(task, r):
    import httpx
    tasks, sync_id, dlq = task
    failing = AsyncMock(side_effect=httpx.ReadTimeout(""))
    with patch.object(tasks, "_crawl_source_async", failing):
        with pytest.raises(Retried):
            run(tasks, sync_id)
        entry = entries(r, sync_id)["a"]
        assert entry["state"] == "retrying" and entry["error"] == "ReadTimeout"  # never a blank error
        assert entry["retry_at"] - time.time() <= tasks.RETRY_DELAYS[0]
        run(tasks, sync_id, retries=len(tasks.RETRY_DELAYS))
    assert entries(r, sync_id)["a"]["state"] == "error"
    assert dlq.call_args.args == ("a", "ReadTimeout")


def test_a_papers_enrichment_waits_in_the_queue_by_its_base_id(r):
    """The crawl, and jobs queued before enrichment was batched, add a paper to the queue; nothing asks yet."""
    from athena.pipeline import crawl
    with patch.object(crawl, "get_redis", return_value=r):
        crawl.queue_enrichment("http://arxiv.org/abs/2610.00001v2", "2610.00001v2")
        crawl.enrich_arxiv_paper.run("http://arxiv.org/abs/2610.00002v1", "2610.00002v1")
    assert [json.loads(p) for p in r.lrange(crawl.ENRICH_QUEUE, 0, -1)] == [
        ["http://arxiv.org/abs/2610.00001v2", "2610.00001"], ["http://arxiv.org/abs/2610.00002v1", "2610.00002"]]


def test_an_enrichment_run_asks_about_its_batch_in_one_lookup(r, monkeypatch):
    from athena.pipeline import crawl
    from athena.scrapers.semanticscholar import SemanticScholarEnricher
    monkeypatch.setattr(crawl, "ENRICH_BATCH", 2)
    for n in (1, 2, 3):
        r.rpush(crawl.ENRICH_QUEUE, json.dumps([f"u{n}", f"2610.0000{n}"]))
    counts = {"2610.00001": {"paper_id": "s2-1", "citation_count": 4, "reference_count": 30}, "2610.00002": None}
    with patch.object(crawl, "get_redis", return_value=r), \
            patch.object(SemanticScholarEnricher, "fetch_many", return_value=counts) as fetch, \
            patch("athena.database.operations.update_content_item_metrics") as update:
        assert crawl.process_enrich_queue.run() == 2
    fetch.assert_called_once_with(["2610.00001", "2610.00002"])
    assert [c.args for c in update.call_args_list] == [("u1", 4, {"semantic_scholar": counts["2610.00001"]}),
                                                       ("u2", 0, {"semantic_scholar": None})]
    assert [json.loads(p)[0] for p in r.lrange(crawl.ENRICH_QUEUE, 0, -1)] == ["u3"]  # the next run's


def test_describe_error_names_the_exception():
    from athena.pipeline.crawl import describe_error
    assert describe_error(ValueError("bad page")) == "ValueError: bad page"
    assert describe_error(TimeoutError()) == "TimeoutError"


# ── scrapers ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lesswrong_is_asked_for_posts_however_the_crawl_calls_it():
    from athena.scrapers.lesswrong import LessWrongScraper
    with patch("httpx.AsyncClient") as cls:
        client = AsyncMock()
        cls.return_value.__aenter__.return_value = client
        resp = MagicMock()
        resp.json.return_value = {"data": {"posts": {"results": [{"title": "t"}]}}}
        client.post = AsyncMock(return_value=resp)
        posts = await LessWrongScraper(source_id=str(uuid4())).fetch("https://www.lesswrong.com/feed.xml")
    assert posts == [{"title": "t"}]
    assert client.post.call_args.kwargs["json"]["variables"] == {"limit": 20}


def test_arxiv_asks_for_each_category_by_category():
    from athena.scrapers.arxiv import ARXIV_DEFAULT_QUERY
    assert ARXIV_DEFAULT_QUERY.split(" OR ") == ["cat:cs.AI", "cat:cs.LG", "cat:cs.CL", "cat:cs.CV", "cat:stat.ML"]


def test_an_arxiv_sync_uses_the_sources_config_and_looks_back_two_days():
    from datetime import datetime, timezone
    from athena.scrapers.arxiv import ARXIV_DEFAULT_QUERY, ARXIV_MAX_PER_SYNC, sync_args
    newest = datetime(2026, 10, 14, 17, 59)  # naive, as SQLite gives it
    assert sync_args({}, newest) == {"search_query": ARXIV_DEFAULT_QUERY, "max_results": ARXIV_MAX_PER_SYNC,
                                     "since": datetime(2026, 10, 12, 17, 59, tzinfo=timezone.utc)}
    assert sync_args(None, None)["since"] is None  # a new source: just the newest page
    mine = sync_args({"query": "cat:cs.RO", "max_results": "300"}, newest)
    assert mine["search_query"] == "cat:cs.RO" and mine["max_results"] == 300
    assert sync_args({"max_results": "lots"}, newest)["max_results"] == ARXIV_MAX_PER_SYNC


def _entry(day: int):
    import xml.etree.ElementTree as ET
    ns = "http://www.w3.org/2005/Atom"
    entry = ET.Element(f"{{{ns}}}entry")
    ET.SubElement(entry, f"{{{ns}}}published").text = f"2026-10-{day:02d}T00:00:00Z"
    return entry


@pytest.mark.asyncio
async def test_arxiv_pages_back_to_the_newest_stored_paper(monkeypatch):
    from datetime import datetime
    from athena.scrapers import arxiv
    monkeypatch.setattr(arxiv, "ARXIV_PAGE_SIZE", 2)
    monkeypatch.setattr(arxiv, "ARXIV_PAGE_DELAY", 0)
    pages = [[_entry(15), _entry(14)], [_entry(13), _entry(12)], [_entry(11), _entry(10)]]
    scraper = arxiv.ArXivScraper(source_id=str(uuid4()))
    scraper._page = AsyncMock(side_effect=pages)
    got = await scraper.fetch(since=datetime(2026, 10, 12), max_results=100)  # stored: naive, as SQLite gives it
    assert [scraper._published(e).day for e in got] == [15, 14, 13, 12]
    assert scraper._page.await_count == 3

    scraper._page = AsyncMock(side_effect=pages)
    capped = await scraper.fetch(since=datetime(2026, 1, 1), max_results=3)
    assert len(capped) == 3


def test_listing_pages_give_their_articles():
    from athena.scrapers.scraping import article_links
    hrefs = [
        "https://www.anthropic.com/news", "https://www.anthropic.com/news/claude-5#top",
        "https://www.anthropic.com/research/x", "https://www.anthropic.com/news/claude-5",
        "https://www.anthropic.com/news/tag/policy", "https://other.com/news/elsewhere",
        "https://www.anthropic.com/news/singapore-office",
    ]
    assert article_links("https://www.anthropic.com/news", hrefs) == [
        "https://www.anthropic.com/news/claude-5", "https://www.anthropic.com/news/singapore-office"]
    assert article_links("https://ai.meta.com/blog/", ["https://ai.meta.com/blog/muse-spark/"]) == [
        "https://ai.meta.com/blog/muse-spark/"]  # as the site writes it


def test_article_pages_give_their_title_date_and_authors():
    from athena.scrapers.scraping import page_meta
    article = {"@type": "Article", "datePublished": "2026-10-06T09:00:00Z", "author": [{"name": "Anthropic"}]}
    ld = json.dumps({"@graph": [{"@type": "WebPage"}, article]})
    meta = page_meta(f'<html><head><meta property="og:title" content="Cyber &amp; you">'
                     f'<script type="application/ld+json">{ld}</script></head><body></body></html>')
    assert meta["title"] == "Cyber & you" and meta["published_at"].day == 6 and meta["authors"] == ["Anthropic"]
    # Meta's blog only prints the date
    meta = page_meta("<html><body><h1>Brain2Qwerty</h1><p>June 29, 2026</p><p>Meta © 2026</p></body></html>")
    assert meta["title"] == "Brain2Qwerty" and meta["published_at"].month == 6 and meta["authors"] == []
