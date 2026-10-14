"""A feed that learns from feedback (ROADMAP P1): reactions, the interest profile, the For-you order, hiding."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import (
    Cluster, ContentCategory, ContentItem, ContentScore, InterestProfile, ItemFeedback, ItemLink, ItemRead,
    SavedList, SavedListItem, ScoringConfig, Source, SourceCategory, SourceType, TrendingBrief, User, UserHighlight,
    UserNote, UserSession,
)
from athena.database import feedback
from athena.pipeline import interests
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

pytestmark = pytest.mark.real_auth

# Three vision papers with low scores, three language papers with high ones.
ITEMS = {"v1": ([1, 0.05, 0], 0.10), "v2": ([1, 0.1, 0], 0.12), "v3": ([1, 0, 0.1], 0.15),
         "n1": ([0, 1, 0.05], 0.40), "n2": ([0.05, 1, 0], 0.45), "n3": ([0, 1, 0.1], 0.50)}


class FakeQdrant:
    """retrieve and query_points over a dict of vectors, cosine similarity."""

    def __init__(self, vectors: dict):
        self.vectors = {k: np.asarray(v, dtype=float) / np.linalg.norm(v) for k, v in vectors.items()}

    def retrieve(self, name, ids, with_vectors=True):
        return [SimpleNamespace(id=i, vector=self.vectors[i].tolist()) for i in ids if i in self.vectors]

    def query_points(self, collection_name, query, limit, query_filter=None, with_payload=False):
        ids = query_filter.must[0].has_id if query_filter else list(self.vectors)
        q = np.asarray(query, dtype=float)
        scored = sorted(((i, float(self.vectors[i] @ q)) for i in ids if i in self.vectors), key=lambda x: -x[1])
        return SimpleNamespace(points=[SimpleNamespace(id=i, score=s) for i, s in scored[:limit]])


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, SavedListItem, Source, Cluster, ContentItem, ContentScore, ItemLink,
                  ItemRead, UserNote, UserHighlight, ItemFeedback, InterestProfile, ScoringConfig, TrendingBrief):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    redis = FakeRedis()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    ids = {}
    with Session() as s:
        source_id = uuid4()
        s.execute(Source.__table__.insert().values(id=source_id, name="ArXiv AI", url="https://export.arxiv.org",
                                                   type=SourceType.API, category=SourceCategory.PAPER,
                                                   fetch_config=None))
        for name, (_, score) in ITEMS.items():
            ids[name] = uuid4()
            s.execute(ContentItem.__table__.insert().values(
                id=ids[name], source_id=source_id, title=name, url=f"https://example.org/{name}", score=score,
                published_at=datetime(2026, 10, 10, tzinfo=timezone.utc), category=ContentCategory.PAPER,
                content_hash=name, authors=None, extra_data={}, is_trending=True))
        s.commit()
    qdrant = FakeQdrant({str(ids[name]): vec for name, (vec, _) in ITEMS.items()})
    monkeypatch.setattr(interests, "_qdrant", lambda: qdrant)
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    yield admin, ids, Session, redis
    app.dependency_overrides.clear()


def titles(c, url="/api/v1/feed?sort=foryou"):
    return [i["title"] for i in c.get(url).json()["items"]]


def react(c, item_id, reaction):
    return c.put(f"/api/v1/items/{item_id}/feedback", json={"reaction": reaction})


def like_vision(c, ids):
    react(c, ids["v1"], "up")
    react(c, ids["v2"], "up")
    lst = c.post("/api/v1/lists", json={"name": "Vision"}).json()
    c.post(f"/api/v1/lists/{lst['id']}/items", json={"item_id": str(ids["v3"])})  # a save counts as liked
    react(c, ids["n1"], "down")
    react(c, ids["n2"], "hide")


# ── reactions and the profile ────────────────────────────────────────


def test_reactions_replace_each_other_and_show_in_the_feed(env):
    admin, ids, _, _ = env
    assert react(admin, ids["v1"], "up").json() == {"reaction": "up"}
    assert react(admin, ids["v1"], "down").status_code == 200
    me = {i["title"]: i["me"]["reaction"] for i in admin.get("/api/v1/feed").json()["items"]}
    assert me["v1"] == "down" and me["v2"] is None
    assert admin.delete(f"/api/v1/items/{ids['v1']}/feedback").status_code == 204
    assert react(admin, uuid4(), "up").status_code == 404
    assert react(admin, ids["v1"], "love").status_code == 422


def test_saves_count_as_liked_unless_a_reaction_says_otherwise(env):
    admin, ids, Session, _ = env
    lst = admin.post("/api/v1/lists", json={"name": "Later"}).json()
    for name in ("v1", "n1"):
        admin.post(f"/api/v1/lists/{lst['id']}/items", json={"item_id": str(ids[name])})
    react(admin, ids["n1"], "down")
    react(admin, ids["v2"], "up")
    with Session() as s:
        user_id = s.query(User).one().id
        liked, disliked = feedback.signals(s, user_id, 300)
    assert set(liked) == {ids["v1"], ids["v2"]} and disliked == [ids["n1"]]
    summary = admin.get("/api/v1/me/interests").json()
    assert summary["counts"] == {"up": 1, "down": 1, "hide": 0, "saved": 1}
    assert summary["signals"] == 3 and summary["ready"] is False and summary["enabled"] is True


def test_the_profile_is_rebuilt_after_a_change(env):
    admin, ids, Session, _ = env
    react(admin, ids["v1"], "up")
    with Session() as s:
        user_id = s.query(User).one().id
        assert s.get(InterestProfile, user_id).embed_model is None  # stale until the next read
        profile = interests.active_profile(s, user_id)
        assert profile.n_positive == 1 and profile.n_negative == 0
        assert np.linalg.norm(profile.positive) == pytest.approx(1.0)
    react(admin, ids["n1"], "down")
    with Session() as s:
        assert s.get(InterestProfile, user_id).embed_model is None


# ── the For-you order ────────────────────────────────────────────────


def test_percentiles_share_ties():
    assert interests.percentiles({"a": 1.0, "b": 1.0, "c": 3.0}) == {"a": 0.25, "b": 0.25, "c": 1.0}
    assert interests.percentiles({"a": 5.0}) == {"a": 0.5}


def test_blend_weighs_the_interest_by_confidence():
    candidates = [("low", 0.1, "paper"), ("high", 0.5, "paper")]
    raw = {"low": 0.9, "high": -0.2}
    assert [r[0] for r in interests.blend(candidates, raw, {"paper": 0.8}, 1.0)] == ["low", "high"]
    assert [r[0] for r in interests.blend(candidates, raw, {"paper": 0.8}, 0.2)] == ["high", "low"]  # w = 0.16


def test_for_you_lifts_what_you_like_and_leaves_out_what_you_hid(env):
    admin, ids, Session, _ = env
    assert titles(admin, "/api/v1/feed") == ["n3", "n2", "n1", "v3", "v2", "v1"]
    like_vision(admin, ids)
    body = admin.get("/api/v1/feed?sort=foryou").json()
    assert body["personalised"] is True
    order = [i["title"] for i in body["items"]]
    assert "n2" not in order                                   # hidden
    assert order.index("v3") < order.index("n1")               # a liked kind beats a disliked one with more score
    assert all(0 <= i["interest"] <= 1 for i in body["items"])
    with Session() as s:  # the admin makes interests count for most of the order
        s.add(ScoringConfig(version=1, category=ContentCategory.PAPER, weight_citation=0.3, weight_engagement=0.15,
                            weight_sentiment=0.15, weight_recency=0.2, weight_authority=0.2, weight_preference=0.8,
                            half_life_days=60, is_active=True))
        s.commit()
    interests.bump(env[3])
    assert set(titles(admin)[:3]) == {"v1", "v2", "v3"}


def test_hidden_items_leave_the_users_lists_only(env):
    admin, ids, _, _ = env
    _, bo = make_user(admin)
    assert len(titles(bo, "/api/v1/feed")) == 6  # warms the shared cache
    react(admin, ids["n3"], "hide")
    assert "n3" not in titles(admin, "/api/v1/feed") and "n3" not in titles(admin, "/api/v1/feed?sort=date")
    assert "n3" not in titles(admin, "/api/v1/trending")
    assert "n3" in titles(bo, "/api/v1/feed") and "n3" in titles(bo, "/api/v1/trending")
    hidden = admin.get("/api/v1/me/feedback?reaction=hide").json()["items"]
    assert [i["title"] for i in hidden] == ["n3"]
    admin.delete(f"/api/v1/items/{ids['n3']}/feedback")  # undo
    assert "n3" in titles(admin, "/api/v1/feed")


def test_switched_off_or_nothing_learned_falls_back_to_the_score(env):
    admin, ids, _, _ = env
    body = admin.get("/api/v1/feed?sort=foryou").json()
    assert body["personalised"] is False and [i["title"] for i in body["items"]][0] == "n3"
    like_vision(admin, ids)
    assert admin.put("/api/v1/me/interests", json={"enabled": False}).json()["enabled"] is False
    body = admin.get("/api/v1/feed?sort=foryou").json()
    assert body["personalised"] is False and "n2" not in [i["title"] for i in body["items"]]  # still hidden
    admin.put("/api/v1/me/interests", json={"enabled": True})
    assert admin.get("/api/v1/feed?sort=foryou").json()["personalised"] is True


def test_qdrant_down_falls_back_to_the_score(env, monkeypatch):
    admin, ids, _, _ = env
    like_vision(admin, ids)

    def down():
        raise ConnectionError("qdrant")
    monkeypatch.setattr(interests, "_qdrant", down)
    body = admin.get("/api/v1/feed?sort=foryou").json()
    assert body["personalised"] is False and body["items"][0]["title"] == "n3"


def test_reset_forgets_reactions_but_saves_still_count(env):
    admin, ids, _, _ = env
    like_vision(admin, ids)
    assert admin.delete("/api/v1/me/feedback").json() == {"removed": 4}
    assert admin.get("/api/v1/me/interests").json()["counts"] == {"up": 0, "down": 0, "hide": 0, "saved": 1}


def test_the_breakdown_adds_your_interests(env):
    admin, ids, Session, _ = env
    with Session() as s:
        s.add(ContentScore(item_id=ids["v3"], citation_score=0.1, engagement_score=0.5, sentiment_score=0.5,
                           recency_score=0.6, authority_score=0.85, composite_score=0.15, score_version=1,
                           computed_at=datetime(2026, 10, 12, tzinfo=timezone.utc)))
        s.commit()
    assert "your_interests" not in admin.get(f"/api/v1/items/{ids['v3']}/score-breakdown").json()["signals"]
    like_vision(admin, ids)
    mine = admin.get(f"/api/v1/items/{ids['v3']}/score-breakdown").json()["signals"]["your_interests"]
    assert mine["score"] > 0.5 and mine["weight"] == pytest.approx(0.3)
