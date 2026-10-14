"""Citation momentum (ROADMAP P3): daily refresh and snapshots, rebuilt history, gains, the routes, and map papers'
citations per year."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import ARRAY, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import (
    AppSetting, ContentCategory, ContentItem, EvoMilestoneOverride, EvoPaper, EvoTopic, EvoTopicPaper, ItemFeedback,
    ItemRead, MetricSnapshot, Source, SourceCategory, SourceType, UserHighlight, UserNote,
)
from athena.database import evolution as evo_db
from athena.database import operations
from athena.evolution import momentum as map_momentum
from athena.pipeline import momentum, scoring
from athena.pipeline.signals import compute_velocity_score
from tests.fakes import FakeRedis

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


@compiles(JSONB, "sqlite")
@compiles(ARRAY, "sqlite")
def _as_json(type_, compiler, **kw):  # Postgres types; SQLite stores them as JSON
    return "JSON"


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Source, ContentItem, MetricSnapshot, AppSetting, EvoTopic, EvoPaper, EvoTopicPaper,
                  EvoMilestoneOverride, ItemRead, UserNote, UserHighlight, ItemFeedback):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    settings: dict[str, str] = {}
    monkeypatch.setattr(momentum, "get_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(momentum, "set_setting", settings.__setitem__)
    factory.settings = settings
    return factory


def add_source(s, url="https://export.arxiv.org/api/query", name="ArXiv AI") -> Source:
    source = Source(id=uuid4(), name=name, url=url, type=SourceType.API, category=SourceCategory.PAPER,
                    fetch_config=None)
    s.add(source)
    s.commit()
    return source


def add_item(s, source, days_old=40, citations=0, category=ContentCategory.PAPER, extra=None, arxiv="2608.00001",
             **fields) -> ContentItem:
    # Core, not the ORM: an explicit None keeps the authors list's Python default out of SQLite.
    item_id = uuid4()
    s.execute(ContentItem.__table__.insert().values(
        id=item_id, source_id=source.id, title=f"Paper {arxiv}", url=f"http://arxiv.org/abs/{arxiv}v1",
        published_at=NOW - timedelta(days=days_old), category=category, content_hash=arxiv, authors=None,
        citation_count=citations, extra_data=extra or {}, **fields))
    s.commit()
    return s.get(ContentItem, item_id)


def snap(s, item, when, count, source="daily"):
    s.add(MetricSnapshot(item_id=item.id, citation_count=count, engagement_raw=0.0, snapshot_date=when,
                         source=source))
    s.commit()


class FakeS2:
    def __init__(self, counts=None, dates=None):
        self.counts = counts or {}      # "ARXIV:..." -> citations
        self.dates = dates or {}        # paper id -> [dates]
        self.asked: list = []

    def get_papers(self, ids, fields=None, max_age=None):
        self.asked.append((list(ids), fields, max_age))
        return {i: SimpleNamespace(paper_id=f"s2-{i}", citation_count=self.counts[i]) if i in self.counts else None
                for i in ids}

    def citation_dates(self, paper_id, max_age=None):
        return self.dates.get(paper_id, [])


# ── scoring fixes ────────────────────────────────────────────────────


def test_metrics_update_merges_into_extra_data(Session, monkeypatch):
    monkeypatch.setattr(operations, "SessionLocal", Session)
    with Session() as s:
        item = add_item(s, add_source(s), citations=4, extra={"arxiv_id": "2608.00001", "pdf_url": "x"})
    operations.update_content_item_metrics(item.url, 0, {"semantic_scholar": None, "papers_with_code": {"r": 1}})
    with Session() as s:
        got = s.get(ContentItem, item.id)
        assert got.extra_data == {"arxiv_id": "2608.00001", "pdf_url": "x", "papers_with_code": {"r": 1}}
        assert got.citation_count == 4  # a failed lookup's 0 doesn't erase what was known


def test_previous_snapshot_is_the_latest_a_week_old_even_with_many(Session):
    with Session() as s:
        item = add_item(s, add_source(s))
        for days in range(20, 0, -1):
            snap(s, item, datetime.now(timezone.utc) - timedelta(days=days), 100 - days)
        assert scoring._get_prev_snapshot(item.id, s) == (93, 0.0)  # 7 days ago; no MultipleResultsFound


def test_without_a_week_old_snapshot_old_items_count_as_unchanged_and_new_ones_as_new(Session):
    with Session() as s:
        source = add_source(s)
        old = add_item(s, source, days_old=40, citations=80, arxiv="2608.00002")
        old.published_at = datetime.now(timezone.utc) - timedelta(days=40)
        new = add_item(s, source, days_old=0, citations=5, arxiv="2608.00003")
        new.published_at = datetime.now(timezone.utc) - timedelta(days=2)
        s.commit()
        assert scoring._week_ago_metrics(old, s, 0.0) == (80, 0.0)
        assert scoring._week_ago_metrics(new, s, 0.0) == (0, 0.0)


def test_full_corpus_runs_stream_every_item_id(Session, monkeypatch):
    monkeypatch.setattr(scoring, "SessionLocal", Session)
    with Session() as s:
        source = add_source(s)
        ids = {add_item(s, source, arxiv=f"2608.0000{i}").id for i in range(3)}
    assert set(scoring._iter_item_ids(select(ContentItem.id))) == ids  # it raised AttributeError before


def test_no_engagement_data_means_no_engagement_velocity():
    assert scoring.engagement_raw([]) == 0.0
    assert compute_velocity_score(0, scoring.engagement_raw([]), 0, 0.0) == 0.0


# ── the daily run ────────────────────────────────────────────────────


def test_refresh_sets_counts_and_keeps_the_rest_of_extra_data(Session):
    with Session() as s:
        source = add_source(s)
        item = add_item(s, source, extra={"arxiv_id": "2608.00001", "semantic_scholar": {"downloadCount": 3}})
        add_item(s, source, days_old=400, arxiv="2508.00009")  # outside the window: not asked about
        s2 = FakeS2({"ARXIV:2608.00001": 12})
        assert momentum.refresh_feed_citations(s, s2, NOW) == 1
        assert s2.asked[0][0] == ["ARXIV:2608.00001"]
        got = s.get(ContentItem, item.id)
        assert got.citation_count == 12
        assert got.extra_data["arxiv_id"] == "2608.00001"
        assert got.extra_data["semantic_scholar"] == {"downloadCount": 3, "paper_id": "s2-ARXIV:2608.00001",
                                                      "citations": 12, "fetched_at": NOW.isoformat()}


def test_rebuilt_points_scale_to_the_true_count_and_start_at_publication():
    points = momentum.rebuilt_points(["2026-07-01", "2026-07-01", "2026-07-05", None, "bad", "2026-06-01"],
                                     date(2026, 6, 20), date(2026, 10, 14), 8)
    # 4 dated citers stand for 8: the one dated before publication counts on the day it was published
    assert points == [(date(2026, 6, 20), 2), (date(2026, 7, 1), 6), (date(2026, 7, 5), 8)]
    assert momentum.rebuilt_points(["2026-10-20"], date(2026, 6, 20), date(2026, 10, 14), 3) == []
    assert momentum.rebuilt_points(["2026-07-01"], date(2026, 6, 20), date(2026, 10, 14), 0) == []


def test_rebuild_fills_only_the_days_before_the_first_daily_snapshot(Session):
    with Session() as s:
        item = add_item(s, add_source(s), days_old=60, citations=9,
                        extra={"semantic_scholar": {"paper_id": "P1"}})
        snap(s, item, NOW - timedelta(days=10), 4)  # the first daily reading: 4 citations then
        s2 = FakeS2(dates={"P1": [(NOW - timedelta(days=d)).date().isoformat() for d in (50, 40, 20, 5, 2)]})
        assert momentum.rebuild_history(s, item, s2, NOW) == 4
        rows = s.execute(select(MetricSnapshot.citation_count, MetricSnapshot.source)
                         .where(MetricSnapshot.item_id == item.id).order_by(MetricSnapshot.snapshot_date)).all()
        assert rows == [(0, "rebuilt"), (1, "rebuilt"), (3, "rebuilt"), (4, "rebuilt"), (4, "daily")]
        assert item.extra_data["semantic_scholar"]["history_rebuilt"] == NOW.isoformat()
        # Run again: it replaces its own rows rather than adding more
        momentum.rebuild_history(s, item, s2, NOW)
        assert s.query(MetricSnapshot).filter_by(item_id=item.id, source="rebuilt").count() == 4


def test_snapshots_are_taken_once_a_day_and_skip_posts_with_nothing_to_measure(Session):
    with Session() as s:
        paper = add_item(s, add_source(s), citations=3)
        blog = add_source(s, "https://openai.com/news/rss.xml", "OpenAI")
        add_item(s, blog, category=ContentCategory.COMPANY_BLOG, arxiv="blog-1")
        lw = add_source(s, "https://www.lesswrong.com/feed.xml", "LessWrong")
        post = add_item(s, lw, category=ContentCategory.COMMUNITY_BLOG, arxiv="lw-1",
                        extra={"karma": 100, "commentCount": 10})
        substack = add_source(s, "https://example.substack.com/feed", "A Substack")
        add_item(s, substack, category=ContentCategory.COMMUNITY_BLOG, arxiv="ss-1")  # no engagement data
        assert momentum.take_snapshots(s, NOW) == 2
        assert momentum.take_snapshots(s, NOW + timedelta(hours=3)) == 0  # same UTC day
        assert {r.item_id for r in s.query(MetricSnapshot)} == {paper.id, post.id}
        assert s.query(MetricSnapshot).filter_by(item_id=post.id).one().engagement_raw == pytest.approx(0.35)
        assert momentum.take_snapshots(s, NOW + timedelta(days=1)) == 2


def test_gains_read_the_history_including_rebuilt_points(Session):
    with Session() as s:
        source = add_source(s)
        paper = add_item(s, source, days_old=60, citations=20)
        snap(s, paper, NOW - timedelta(days=45), 2, "rebuilt")
        snap(s, paper, NOW - timedelta(days=20), 10, "rebuilt")
        snap(s, paper, NOW - timedelta(days=8), 15)
        young = add_item(s, source, days_old=3, citations=4, arxiv="2610.00001")
        unknown = add_item(s, source, days_old=50, citations=7, arxiv="2608.00004")
        gone = add_item(s, source, days_old=500, arxiv="2506.00001", citation_gain_7d=3, citation_gain_30d=5)
        momentum.update_gains(s, NOW)
        assert (paper.citation_gain_7d, paper.citation_gain_30d) == (5, 18)
        assert (young.citation_gain_7d, young.citation_gain_30d) == (4, 4)
        assert unknown.citation_gain_7d is None  # no reading from a week ago
        s.refresh(gone)
        assert gone.citation_gain_7d is None and gone.citation_gain_30d is None


def test_series_carries_values_forward_and_prefers_a_daily_reading(Session):
    with Session() as s:
        paper = add_item(s, add_source(s), days_old=5, citations=3)
        snap(s, paper, NOW - timedelta(days=4), 1, "rebuilt")
        snap(s, paper, NOW - timedelta(days=2), 2, "rebuilt")
        snap(s, paper, NOW - timedelta(days=2, hours=-1), 3)
        out = momentum.series(s, paper, NOW, days=4)
        assert [(p["citations"], p["rebuilt"]) for p in out] == [(1, True), (3, False), (3, False), (3, False)]


def test_run_still_snapshots_when_semantic_scholar_fails(Session):
    class Down(FakeS2):
        def get_papers(self, *a, **k):
            raise RuntimeError("429")
    with Session() as s:
        add_item(s, add_source(s), citations=2)
        summary = momentum.run(s, Down(), NOW)
    assert summary["refreshed"] == 0 and summary["snapshots"] == 1


def test_the_hourly_task_works_once_a_day(Session, monkeypatch):
    import athena.database.db as db_module
    calls = []
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(momentum, "run", lambda session, s2, now, rebuilds=30: calls.append(now) or {"ok": 1})
    monkeypatch.setattr("athena.evolution.semantic_scholar.SemanticScholarClient", lambda: None)
    assert momentum.daily_momentum() == {"ok": 1}
    assert momentum.daily_momentum() == {"skipped": datetime.now(timezone.utc).date().isoformat()}
    assert len(calls) == 1
    assert momentum.daily_momentum(force=True) == {"ok": 1}


# ── routes ───────────────────────────────────────────────────────────


@pytest.fixture
def api(Session):
    redis = FakeRedis()

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_redis, None)


def test_item_momentum_route(Session, api):
    with Session() as s:
        source = add_source(s)
        paper = add_item(s, source, days_old=3, citations=6, citation_gain_7d=6, citation_gain_30d=6,
                         extra={"semantic_scholar": {"fetched_at": "2026-10-14T00:00:00+00:00"}})
        snap(s, paper, datetime.now(timezone.utc) - timedelta(days=1), 6)
        blog = add_item(s, source, category=ContentCategory.COMPANY_BLOG, arxiv="blog-2")
        paper_id, blog_id = paper.id, blog.id
    body = api.get(f"/api/v1/items/{paper_id}/momentum").json()
    assert body["total"] == 6 and body["gain_7d"] == 6 and body["fetched_at"].startswith("2026-10-14")
    assert body["series"][-1]["citations"] == 6
    assert api.get(f"/api/v1/items/{blog_id}/momentum").json()["series"] == []
    assert api.get(f"/api/v1/items/{uuid4()}/momentum").status_code == 404


def test_rising_lists_papers_by_gain(Session, api):
    with Session() as s:
        source = add_source(s)
        add_item(s, source, citations=10, citation_gain_7d=2, citation_gain_30d=9, arxiv="a")
        add_item(s, source, citations=30, citation_gain_7d=7, citation_gain_30d=8, arxiv="b")
        add_item(s, source, citations=1, citation_gain_7d=0, citation_gain_30d=1, arxiv="c")
    week = api.get("/api/v1/momentum/rising?window=7d").json()
    assert [(i["title"], i["gain"]) for i in week["items"]] == [("Paper b", 7), ("Paper a", 2)]
    assert "series" in week["items"][0] and week["items"][0]["citation_gain_7d"] == 7
    month = api.get("/api/v1/momentum/rising?window=30d").json()
    assert [i["title"] for i in month["items"]] == ["Paper a", "Paper b", "Paper c"]
    assert api.get("/api/v1/momentum/rising?window=1y").status_code == 422


# ── map papers ───────────────────────────────────────────────────────


def test_twelve_months_from_calendar_years():
    counts = {2024: 40, 2025: 100, 2026: 150}
    january = datetime(2026, 1, 2, tzinfo=timezone.utc)
    last, before = map_momentum.twelve_months(counts, january)
    assert last == pytest.approx(150 + 100 * (1 - 1 / 365), abs=0.5)  # January keeps most of last year
    assert before == pytest.approx(40, abs=1)
    october = datetime(2026, 10, 1, tzinfo=timezone.utc)
    last, before = map_momentum.twelve_months(counts, october)
    assert last == pytest.approx(150 + 100 * 0.25, abs=1)
    assert before == pytest.approx(100 * 0.75 + 40 * 0.25, abs=1)


def test_rising_needs_enough_citations_and_growth():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert map_momentum.rising_entry({2026: 5}, now) is None                 # under the floor
    assert map_momentum.rising_entry({2025: 400, 2026: 100}, now) is None    # falling
    entry = map_momentum.rising_entry({2025: 10, 2026: 60}, now)
    assert entry["last_12_months"] == 63 and entry["ratio"] > 3
    years = map_momentum.by_year({2026: 3}, now, years=3)
    assert years == [{"year": 2024, "citations": 0, "partial": False}, {"year": 2025, "citations": 0, "partial": False},
                     {"year": 2026, "citations": 3, "partial": True}]


def add_topic(s):
    topic_id = uuid4()
    s.execute(EvoTopic.__table__.insert().values(id=topic_id, slug="peft", name="PEFT", status="ready", aliases=None,
                                                 seeds=None, config=None, built_at=NOW))
    papers = []
    for i, extra in enumerate([{"counts_by_year": {"2025": 10, "2026": 90}}, {"counts_by_year": {"2026": 20}},
                               {"counts_by_year": {"2024": 500, "2025": 400, "2026": 100}}, {}]):
        pid = uuid4()
        s.execute(EvoPaper.__table__.insert().values(id=pid, openalex_id=f"W{i}", title=f"Paper {i}", year=2024,
                                                     authors=None, authorships=None, merged_ids=None, extra=extra))
        s.execute(EvoTopicPaper.__table__.insert().values(id=uuid4(), topic_id=topic_id, paper_id=pid,
                                                          score_detail=None))
        papers.append(pid)
    s.commit()
    return s.get(EvoTopic, topic_id), papers


def test_topic_rising_ranks_by_growth(Session, monkeypatch):
    monkeypatch.setattr(evo_db, "method_names", lambda session, papers: {})
    with Session() as s:
        topic, papers = add_topic(s)
        rising = evo_db.topic_rising(s, topic, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert [r["title"] for r in rising] == ["Paper 0", "Paper 1"]
    assert rising[0]["citations_by_year"][-1] == {"year": 2026, "citations": 90, "partial": True}


def test_refresh_topic_years_fetches_only_what_is_due(Session):
    class FakeOpenAlex:
        def __init__(self):
            self.asked = []

        def citation_years(self, ids):
            self.asked.append(ids)
            return {"W0": {2026: 95}, "W3": {2025: 1}}
    with Session() as s:
        topic, papers = add_topic(s)
        s.get(EvoPaper, papers[1]).extra = {"counts_by_year": {"2026": 20},
                                            "counts_fetched_at": (NOW - timedelta(days=3)).isoformat()}
        s.commit()
        client = FakeOpenAlex()
        assert map_momentum.refresh_topic_years(s, topic, client, now=NOW) == 3
        assert sorted(client.asked[0]) == ["W0", "W2", "W3"]
        assert s.get(EvoPaper, papers[0]).extra["counts_by_year"] == {"2026": 95}
        missing = s.get(EvoPaper, papers[2]).extra  # OpenAlex didn't answer: keeps its counts, waits a month
        assert missing["counts_by_year"] == {"2024": 500, "2025": 400, "2026": 100}
        assert missing["counts_fetched_at"] == NOW.isoformat()
        assert map_momentum.refresh_topic_years(s, topic, client, now=NOW) == 0
