"""A feed that isn't half one source (ROADMAP_v2 T3): the per-source cap on Score and For-you pages."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.api.routers import feed
from athena.api.routers.feed import diversify
from athena.core.models import (
    AppSetting, Cluster, ContentCategory, ContentItem, ItemFeedback, ItemLink, ItemRead, SavedList, SavedListItem,
    Source, SourceCategory, SourceType, UserHighlight, UserNote,
)
from tests.fakes import FakeRedis


def rows(**counts) -> list[tuple[str, int]]:
    """Rows in score order: every row of the first source, then the next one's, and so on."""
    return [(source, i) for source, n in counts.items() for i in range(n)]


def pages(order, limit):
    return [order[i:i + limit] for i in range(0, len(order), limit)]


# ── diversify ────────────────────────────────────────────────────────


def test_no_source_fills_more_than_its_share_while_others_are_left():
    order = diversify(rows(a=10, b=3, c=3), lambda r: r[0], limit=4, share=0.5, upto=16)
    assert [[s for s, _ in p] for p in pages(order, 4)] == [
        ["a", "a", "b", "b"], ["a", "a", "b", "c"], ["a", "a", "c", "c"], ["a", "a", "a", "a"]]


def test_nothing_is_lost_or_repeated_and_each_source_keeps_its_order():
    data = rows(a=37, b=5, c=11, d=2)
    order = diversify(data, lambda r: r[0], limit=7, share=0.25, upto=len(data))
    assert sorted(order) == sorted(data)
    for source in "abcd":
        assert [i for s, i in order if s == source] == sorted(i for s, i in order if s == source)


def test_a_page_is_the_same_however_far_it_is_computed():
    data = rows(a=30, b=6, c=6)
    full = diversify(data, lambda r: r[0], limit=5, share=0.4, upto=len(data))
    for page in range(1, 9):
        assert diversify(data, lambda r: r[0], limit=5, share=0.4, upto=page * 5) == full[:page * 5]


def test_a_cap_under_one_row_still_lets_one_through_and_one_source_fills_the_page():
    assert diversify(rows(a=3, b=1), lambda r: r[0], limit=2, share=0.1, upto=4) == [
        ("a", 0), ("b", 0), ("a", 1), ("a", 2)]
    assert diversify(rows(a=5), lambda r: r[0], limit=3, share=0.25, upto=5) == rows(a=5)


@pytest.mark.parametrize("raw, share", [("0.4", 0.4), ("1", 1.0), ("3", 1.0), ("0", 0.25), ("x", 0.25), ("", 0.25)])
def test_source_share_setting(monkeypatch, raw, share):
    monkeypatch.setattr(feed, "get_setting", lambda key, default="": raw or default)
    assert feed.source_share() == share


# ── the feed route ───────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Source, Cluster, ContentItem, ItemLink, ItemRead, UserNote, UserHighlight, ItemFeedback, SavedList,
                  SavedListItem, AppSetting):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    setting = {"share": "0.25"}
    monkeypatch.setattr(feed, "get_setting", lambda key, default="": setting["share"])
    with Session() as s:
        sources = {}
        for name, n, base in (("OpenAI News", 12, 0.9), ("NVIDIA Blog", 3, 0.5), ("ArXiv AI", 3, 0.4),
                              ("LessWrong", 2, 0.3)):
            sources[name] = uuid4()
            s.execute(Source.__table__.insert().values(id=sources[name], name=name, url=f"https://{n}.example/{name}",
                                                       type=SourceType.RSS, category=SourceCategory.COMPANY))
            for i in range(n):
                s.execute(ContentItem.__table__.insert().values(
                    id=uuid4(), source_id=sources[name], title=f"{name} {i}", url=f"https://example.org/{name}/{i}",
                    score=base - i * 0.001, published_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
                    category=ContentCategory.COMPANY_BLOG, content_hash=f"{name}{i}", authors=None, extra_data={}))
        s.commit()
    yield TestClient(app), sources, setting, Session
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_redis, None)


def source_names(body):
    return [i["source"]["name"] for i in body["items"]]


def test_the_score_feed_caps_each_source_per_page(env):
    client, sources, *_ = env
    first = client.get("/api/v1/feed?limit=8").json()
    names = source_names(first)
    assert names.count("OpenAI News") == 2 and set(names) == {"OpenAI News", "NVIDIA Blog", "ArXiv AI", "LessWrong"}
    assert first["pagination"] == {"page": 1, "limit": 8, "total": 20, "has_next": True}
    seen = [i["id"] for p in (1, 2, 3) for i in client.get(f"/api/v1/feed?limit=8&page={p}").json()["items"]]
    assert len(seen) == 20 and len(set(seen)) == 20  # infinite scroll skips and repeats nothing


def test_date_order_and_no_cap_keep_the_plain_order(env):
    client, _, setting, _ = env
    by_date = client.get("/api/v1/feed?sort=date&limit=8").json()
    assert len(by_date["items"]) == 8
    setting["share"] = "1"
    assert source_names(client.get("/api/v1/feed?limit=8").json()) == ["OpenAI News"] * 8


def test_the_cap_is_a_setting(env):
    client, _, _, Session = env
    assert client.get("/api/v1/settings/feed").json() == {"source_share": 0.25, "default_source_share": 0.25}
    assert client.put("/api/v1/settings/feed", json={"source_share": 0.5}).json()["source_share"] == 0.5
    with Session() as s:
        assert s.get(AppSetting, "FEED_SOURCE_SHARE").value == "0.5"
    for bad in (0, 1.5, -0.1):
        assert client.put("/api/v1/settings/feed", json={"source_share": bad}).status_code == 422


def test_for_you_pages_are_capped_too(env):
    _, _, _, Session = env
    with Session() as s:
        items = s.query(ContentItem).order_by(ContentItem.score.desc()).all()
        order = [[str(i.id), 0.5, 0.5] for i in items]  # what interests.ranked caches: id, for-you, interest
        page = feed._ranked_page(s, order, 1, 8, 0.25)
        assert source_names(page).count("OpenAI News") == 2 and page["pagination"]["total"] == 20
        assert source_names(feed._ranked_page(s, order, 1, 8))[:8] == ["OpenAI News"] * 8  # no cap
