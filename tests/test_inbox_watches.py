"""Follows (watches), what they catch, the digest, who sees which inbox entry, and the routes."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from athena.api.deps import get_db
from athena.api.main import app
from athena.database import inbox as inbox_db
from athena.database import watches as watch_db
from athena.pipeline import watches as pipe
from tests.conftest import ADMIN

MONDAY = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
TUESDAY = MONDAY + timedelta(days=1)


# ── digest schedule and wording ──────────────────────────────────────


def settings(**kw):
    return {"digest": "weekly", "digest_day": 0, "muted_kinds": [], "last_digest_at": None} | kw


@pytest.mark.parametrize("s,now,due", [
    (settings(digest="off"), MONDAY, False),
    (settings(digest="daily"), TUESDAY, True),
    (settings(), MONDAY, True),
    (settings(), TUESDAY, False),
    (settings(digest_day=1), TUESDAY, True),
    (settings(last_digest_at=MONDAY - timedelta(hours=2)), MONDAY, False),   # never twice in a day
    (settings(digest="daily", last_digest_at=TUESDAY - timedelta(hours=21)), TUESDAY, True),
])
def test_digests_come_on_their_schedule(s, now, due):
    assert pipe.is_due(s, now) is due


def test_a_digest_covers_the_time_since_the_last_one_within_reason():
    assert pipe.period_start(settings(), MONDAY) == MONDAY - timedelta(days=7)
    assert pipe.period_start(settings(digest="daily"), MONDAY) == MONDAY - timedelta(days=1)
    assert pipe.period_start(settings(last_digest_at=MONDAY - timedelta(days=9)), MONDAY) == MONDAY - timedelta(days=9)
    long_ago = settings(last_digest_at=MONDAY - timedelta(days=90))  # digests were off for months
    assert pipe.period_start(long_ago, MONDAY) == MONDAY - timedelta(days=14)


def test_digest_titles():
    wed = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)
    assert pipe.digest_title("daily", wed - timedelta(days=1), wed) == "Your daily digest · Wed 14 Oct"
    assert pipe.digest_title("weekly", wed - timedelta(days=7), wed) == "Your weekly digest · 7–13 Oct"
    oct6 = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
    assert pipe.digest_title("weekly", oct6 - timedelta(days=7), oct6) == "Your weekly digest · 29 Sep – 5 Oct"


def payload(**kw):
    return {"watches": [], "maps": [], "new_maps": [], "citations": [], "top_papers": []} | kw


def test_digest_body_says_what_each_section_holds():
    p = payload(watches=[{"count": 4}, {"count": 2}], maps=[{"name": "PEFT"}, {"name": "PEFT"}, {"name": "RAG"}],
                new_maps=[{}], citations=[{"items": [{}, {}]}], top_papers=[{"title": "DoRA 2"}])
    assert pipe.digest_body(p) == ("6 new from 2 watches · PEFT, RAG updated · 1 new map · "
                                   "2 papers cite milestones · top new: DoRA 2")
    assert pipe.digest_is_empty(payload()) and not pipe.digest_is_empty(p)


def test_an_empty_digest_is_not_sent():
    with patch.object(pipe, "build_digest", return_value=payload()), \
            patch("athena.database.inbox.add_event") as add:
        assert pipe.send_digest(None, ADMIN, settings(), MONDAY) is False
    add.assert_not_called()


# ── watch checks ─────────────────────────────────────────────────────


@pytest.mark.parametrize("kind,n,label,title", [
    ("search", 3, "video diffusion", '3 new matches for "video diffusion"'),
    ("search", 1, "video diffusion", '1 new match for "video diffusion"'),
    ("source", 5, "The Gradient", "5 new from The Gradient"),
    ("cluster", 4, "LLM agents", '4 new in "LLM agents"'),
])
def test_watch_entry_titles(kind, n, label, title):
    assert pipe.matches_title(kind, n, label) == title


def watch(**kw):
    base = {"id": uuid4(), "user_id": ADMIN.id, "kind": "search", "delivery": "instant", "query": "rag",
            "query_vector": [0.1], "embed_model": "qwen3-embedding-8b", "checked_at": None,
            "created_at": MONDAY, "source_id": None, "cluster_id": None}
    return SimpleNamespace(**(base | kw))


INFO = {"label": "rag", "link": "/search?q=rag", "status": "active"}


@pytest.mark.parametrize("delivery,new,announced", [
    ("instant", {"a", "b"}, True),
    ("digest", {"a", "b"}, False),   # recorded for the digest only
    ("instant", set(), False),       # nothing new: no entry
])
def test_a_watch_announces_only_new_items_and_only_as_it_happens(delivery, new, announced):
    w = watch(delivery=delivery)
    items = [{"id": i, "title": f"Paper {i}", "score": 0.5, "similarity": 0.7} for i in sorted(new)]
    with patch.object(pipe, "search_hits", return_value={"a": 0.7, "b": 0.7, "old": 0.8}), \
            patch("athena.database.watches.add_hits", return_value=new) as add_hits, \
            patch.object(pipe, "_items", return_value=items), \
            patch("athena.database.inbox.add_event") as add:
        assert pipe.check_watch(None, w, TUESDAY, None, INFO) == len(new)
    assert add_hits.call_args.args[2] == {"a": 0.7, "b": 0.7, "old": 0.8}
    assert add.called is announced
    if announced:
        assert add.call_args.args[1:3] == ("watch_matches", '2 new matches for "rag"')
        assert add.call_args.kwargs["user_id"] == ADMIN.id
    assert w.checked_at == TUESDAY


def test_a_search_compares_only_new_items_and_keeps_those_above_the_floor():
    ids = [uuid4(), uuid4()]
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = ids
    qdrant = MagicMock()
    qdrant.query_points.return_value.points = [SimpleNamespace(id=str(ids[0]), score=0.71234)]
    w = watch(embed_model="old-model")
    with patch("athena.core.llm.embed_model", return_value="qwen3-embedding-8b"), \
            patch("athena.search.local.embed_query", return_value=[0.9]) as embed:
        assert pipe.search_hits(session, w, TUESDAY, qdrant) == {ids[0]: 0.7123}
    kwargs = qdrant.query_points.call_args.kwargs
    assert kwargs["score_threshold"] == pipe.SEARCH_FLOOR
    assert kwargs["query_filter"].must[0].has_id == [str(i) for i in ids]
    embed.assert_called_once_with("rag")  # the feed's embedding model changed, so the query is embedded again
    assert (w.query_vector, w.embed_model) == ([0.9], "qwen3-embedding-8b")


def test_a_search_with_no_new_items_asks_qdrant_nothing():
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    qdrant = MagicMock()
    assert pipe.search_hits(session, watch(), TUESDAY, qdrant) == {}
    qdrant.query_points.assert_not_called()


def test_one_broken_watch_does_not_stop_the_others():
    watches = [watch(kind="source"), watch(kind="cluster")]
    session = MagicMock()
    with patch("athena.database.db.SessionLocal", return_value=MagicMock(__enter__=lambda s: session)), \
            patch("athena.database.watches.checkable", return_value=watches), \
            patch("athena.database.watches.describe", return_value={w.id: INFO for w in watches}), \
            patch.object(pipe, "check_watch", side_effect=[RuntimeError("Qdrant is down"), 3]):
        assert pipe.run_checks(qdrant=MagicMock()) == {"watches": 1, "caught": 3, "failed": 1}
    session.rollback.assert_called_once()


# ── who sees what ────────────────────────────────────────────────────


def sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_users_see_their_own_entries_new_maps_and_the_maps_they_follow():
    text = sql(inbox_db._visible(ADMIN, []))
    assert "inbox_events.user_id = " in text and "inbox_events.user_id IS NULL" in text
    assert "inbox_events.kind = 'map_new'" in text
    assert "watches.delivery = 'instant'" in text and "watches.kind = 'map'" in text
    assert "NOT IN" not in text
    assert "inbox_events.kind NOT IN ('map_new', 'feed_citations')" in sql(
        inbox_db._visible(ADMIN, ["map_new", "feed_citations"]))


def test_feed_papers_citing_milestones_make_one_entry_per_map():
    from athena.evolution import feedlink
    peft, rag = uuid4(), uuid4()
    lora = {"topic": "peft", "topic_name": "PEFT", "named_method": "LoRA", "title": "LoRA"}
    dpr = {"topic": "rag", "topic_name": "RAG", "named_method": None, "title": "Dense Passage Retrieval"}
    citing = [(SimpleNamespace(id=uuid4(), title="Paper A"), [lora, dpr]),
              (SimpleNamespace(id=uuid4(), title="Paper B"), [lora])]
    with patch.object(feedlink, "_topic_ids", return_value={"peft": peft, "rag": rag}), \
            patch("athena.database.inbox.add_event") as add:
        feedlink.announce(None, citing)
    calls = {c.args[5]: c.args for c in add.call_args_list}
    assert calls[peft][1:5] == ("feed_citations", "2 new papers cite milestones of PEFT", "Paper A; Paper B",
                                "/evolution/peft")
    assert calls[rag][2] == "1 new paper cites milestones of RAG"
    assert calls[rag][6]["items"] == [{"id": str(citing[0][0].id), "title": "Paper A",
                                       "cites": ["Dense Passage Retrieval"]}]


def test_search_targets_ignore_case_and_spacing():
    assert watch_db.target_for("search", "  Video   Diffusion ") == "search:video diffusion"
    topic = uuid4()
    assert watch_db.target_for("map", topic) == f"map:{topic}"


# ── routes ───────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self, exists=True):
        self.exists = exists

    def get(self, model, ref):
        return SimpleNamespace(id=ref) if self.exists else None


@pytest.fixture
def client():
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app), session
    app.dependency_overrides.pop(get_db, None)


def saved(kind="map", **kw):
    return SimpleNamespace(id=uuid4(), kind=kind, target=f"{kind}:x", topic_id=uuid4(), source_id=None,
                           cluster_id=None, query=None, delivery="instant", created_at=MONDAY, **kw)


DESCRIBED = {"label": "PEFT", "link": "/evolution/peft", "status": "active"}


def test_following_a_map(client):
    c, _ = client
    w = saved()
    with patch("athena.database.watches.follow", return_value=(w, True)) as follow, \
            patch("athena.database.watches.describe", return_value={w.id: DESCRIBED}):
        resp = c.post("/api/v1/watches", json={"kind": "map", "topic_id": str(w.topic_id)})
    assert resp.status_code == 201
    assert resp.json()["label"] == "PEFT" and resp.json()["ref"] == str(w.topic_id)
    assert follow.call_args.args[1] is ADMIN and follow.call_args.kwargs["topic_id"] == w.topic_id


def test_following_again_is_not_an_error(client):
    c, _ = client
    w = saved()
    with patch("athena.database.watches.follow", return_value=(w, False)), \
            patch("athena.database.watches.describe", return_value={w.id: DESCRIBED}):
        assert c.post("/api/v1/watches", json={"kind": "map", "topic_id": str(w.topic_id)}).status_code == 200


def test_following_a_search_embeds_its_query_once(client):
    c, _ = client
    w = saved("search", )
    with patch("athena.database.watches.find", return_value=None), \
            patch("athena.search.local.embed_query", return_value=[0.5]) as embed, \
            patch("athena.core.llm.embed_model", return_value="qwen3-embedding-8b"), \
            patch("athena.database.watches.follow", return_value=(w, True)) as follow, \
            patch("athena.database.watches.describe", return_value={w.id: DESCRIBED}):
        assert c.post("/api/v1/watches", json={"kind": "search", "query": " video  diffusion "}).status_code == 201
    embed.assert_called_once_with("video diffusion")
    assert follow.call_args.kwargs["vector"] == [0.5]
    with patch("athena.database.watches.find", return_value=w), \
            patch("athena.search.local.embed_query") as embed, \
            patch("athena.database.watches.follow", return_value=(w, False)), \
            patch("athena.database.watches.describe", return_value={w.id: DESCRIBED}):
        assert c.post("/api/v1/watches", json={"kind": "search", "query": "video diffusion"}).status_code == 200
    embed.assert_not_called()


def test_a_search_cannot_be_followed_without_the_embedding_model(client):
    c, _ = client
    with patch("athena.database.watches.find", return_value=None), \
            patch("athena.search.local.embed_query", side_effect=ConnectionError("down")):
        assert c.post("/api/v1/watches", json={"kind": "search", "query": "video diffusion"}).status_code == 503


def test_follow_requests_need_their_target(client):
    c, session = client
    assert c.post("/api/v1/watches", json={"kind": "map"}).status_code == 422
    assert c.post("/api/v1/watches", json={"kind": "search", "query": "   "}).status_code == 422
    assert c.post("/api/v1/watches", json={"kind": "map", "topic_id": str(uuid4()),
                                           "delivery": "hourly"}).status_code == 422
    session.exists = False
    assert c.post("/api/v1/watches", json={"kind": "source", "source_id": str(uuid4())}).status_code == 404


def test_following_has_a_limit(client):
    c, _ = client
    with patch("athena.database.watches.follow", side_effect=watch_db.WatchLimit()):
        assert c.post("/api/v1/watches", json={"kind": "cluster", "cluster_id": str(uuid4())}).status_code == 409


def test_another_users_watch_is_not_found(client):
    c, _ = client
    with patch("athena.database.watches.set_delivery", return_value=None) as set_delivery, \
            patch("athena.database.watches.unfollow", return_value=False):
        assert c.patch(f"/api/v1/watches/{uuid4()}", json={"delivery": "digest"}).status_code == 404
        assert c.delete(f"/api/v1/watches/{uuid4()}").status_code == 404
    assert set_delivery.call_args.args[1] is ADMIN


def test_listing_and_unfollowing(client):
    c, _ = client
    with patch("athena.database.watches.list_for", return_value=[{"id": "w"}]), \
            patch("athena.database.watches.unfollow", return_value=True):
        assert c.get("/api/v1/watches").json() == {"watches": [{"id": "w"}], "limit": watch_db.MAX_WATCHES}
        assert c.delete(f"/api/v1/watches/{uuid4()}").status_code == 204


def test_inbox_settings(client):
    c, _ = client
    stored = settings(digest="daily", muted_kinds=["map_new"], last_digest_at=MONDAY)
    with patch("athena.database.inbox.save_settings") as save, \
            patch("athena.database.inbox.get_settings", return_value=stored):
        body = c.put("/api/v1/inbox/settings", json={"digest": "daily", "digest_day": 3,
                                                     "muted_kinds": ["map_new", "map_new"]}).json()
        assert c.get("/api/v1/inbox/settings").json() == body
    assert save.call_args.kwargs == {"digest": "daily", "digest_day": 3, "muted_kinds": ["map_new"]}
    assert body["last_digest_at"] == MONDAY.isoformat()
    assert c.put("/api/v1/inbox/settings", json={"digest": "hourly"}).status_code == 422
    assert c.put("/api/v1/inbox/settings", json={"digest": "weekly", "digest_day": 7}).status_code == 422
    assert c.put("/api/v1/inbox/settings", json={"digest": "weekly", "muted_kinds": ["digest"]}).status_code == 422
