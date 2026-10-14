"""Reading state (ROADMAP P2): read marks, notes and highlights on feed items and map papers, per user."""
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
from athena.core.models import (
    Cluster, ContentCategory, ContentItem, EvoPaper, EvoReadingProgress, EvoTopic, EvoTopicPaper, ItemLink, ItemRead,
    SavedList, SavedListItem, Source, SourceCategory, SourceType, User, UserHighlight, UserNote, UserSession,
)
from athena.database.personal import anchor
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

pytestmark = pytest.mark.real_auth

ABSTRACT = "We study low-rank adapters. Low-rank adapters cut memory. We show adapters match full tuning."


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, SavedListItem, Source, Cluster, ContentItem, ItemLink, EvoTopic,
                  EvoPaper, EvoTopicPaper, EvoReadingProgress, ItemRead, UserNote, UserHighlight):
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
        for name, days in (("lora", 1), ("dora", 2)):
            ids[name] = uuid4()
            s.execute(ContentItem.__table__.insert().values(
                id=ids[name], source_id=source_id, title=name.upper(), url=f"http://arxiv.org/abs/{name}",
                published_at=datetime(2026, 10, 14 - days, tzinfo=timezone.utc), category=ContentCategory.PAPER,
                content_hash=name, authors=None, extra_data={}, score=0.5 - days / 10, abstract=ABSTRACT,
                summary="Adapters are cheap.", takeaways=["Small", "Fast"]))
        ids["topic"] = uuid4()
        s.execute(EvoTopic.__table__.insert().values(id=ids["topic"], slug="peft", name="PEFT", status="ready",
                                                     aliases=None, seeds=None, config=None,
                                                     built_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        for name, linked in (("paper_lora", ids["lora"]), ("paper_old", None)):
            ids[name] = uuid4()
            s.execute(EvoPaper.__table__.insert().values(
                id=ids[name], openalex_id=name, title=name, year=2021, authors=None, authorships=None,
                merged_ids=None, extra=None, abstract=ABSTRACT, content_item_id=linked))
            s.execute(EvoTopicPaper.__table__.insert().values(id=uuid4(), topic_id=ids["topic"], paper_id=ids[name],
                                                              score_detail=None))
        s.commit()
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    _, bo = make_user(admin)
    yield admin, bo, ids, Session
    app.dependency_overrides.clear()


def me(c, item_id):
    return c.get(f"/api/v1/items/{item_id}/me").json()


# ── read marks ───────────────────────────────────────────────────────


def test_read_marks_are_per_user_and_show_in_lists(env):
    admin, bo, ids, _ = env
    assert admin.put(f"/api/v1/items/{ids['lora']}/read").status_code == 204
    assert me(admin, ids["lora"])["read"] is True and me(bo, ids["lora"])["read"] is False
    feed = {i["title"]: i["me"] for i in admin.get("/api/v1/feed").json()["items"]}
    assert feed == {"LORA": {"read": True, "annotated": False, "reaction": None},
                    "DORA": {"read": False, "annotated": False, "reaction": None}}
    assert [i["title"] for i in admin.get("/api/v1/feed?unread=true").json()["items"]] == ["DORA"]
    assert len(bo.get("/api/v1/feed?unread=true").json()["items"]) == 2  # the filtered page isn't shared
    assert admin.delete(f"/api/v1/items/{ids['lora']}/read").status_code == 204
    assert me(admin, ids["lora"])["read"] is False
    assert admin.put(f"/api/v1/items/{uuid4()}/read").status_code == 404


def test_a_feed_item_and_its_map_paper_are_read_together(env):
    admin, _, ids, _ = env
    admin.put(f"/api/v1/items/{ids['lora']}/read")
    assert admin.get(f"/api/v1/evolution/papers/{ids['paper_lora']}/me").json()["read"] is True
    admin.delete(f"/api/v1/evolution/papers/{ids['paper_lora']}/read")
    assert me(admin, ids["lora"])["read"] is False
    admin.put(f"/api/v1/evolution/papers/{ids['paper_old']}/read")  # not in the feed: only the paper
    assert admin.get(f"/api/v1/evolution/papers/{ids['paper_old']}/me").json()["read"] is True


def test_saved_lists_count_what_was_read(env):
    admin, _, ids, _ = env
    lst = admin.post("/api/v1/lists", json={"name": "Adapters"}).json()
    for name in ("lora", "dora"):
        admin.post(f"/api/v1/lists/{lst['id']}/items", json={"item_id": str(ids[name])})
    admin.put(f"/api/v1/items/{ids['dora']}/read")
    assert admin.get("/api/v1/lists").json()[0]["read_count"] == 1
    items = admin.get(f"/api/v1/lists/{lst['id']}/items?unread=true").json()["items"]
    assert [i["title"] for i in items] == ["LORA"] and items[0]["me"]["read"] is False


# ── notes ────────────────────────────────────────────────────────────


def test_notes_are_private_and_an_empty_one_is_removed(env):
    admin, bo, ids, _ = env
    saved = admin.put(f"/api/v1/items/{ids['lora']}/note", json={"body": "  Compare with DoRA.  "}).json()
    assert saved["note"]["body"] == "Compare with DoRA."
    assert me(admin, ids["lora"])["note"]["body"] == "Compare with DoRA."
    assert me(bo, ids["lora"])["note"] is None
    assert admin.get("/api/v1/feed").json()["items"][0]["me"]["annotated"] is True
    assert admin.put(f"/api/v1/items/{ids['lora']}/note", json={"body": ""}).json() == {"note": None}
    assert me(admin, ids["lora"])["note"] is None
    paper = admin.put(f"/api/v1/evolution/papers/{ids['paper_old']}/note", json={"body": "Seminal"}).json()
    assert paper["note"]["body"] == "Seminal"
    assert admin.delete(f"/api/v1/evolution/papers/{ids['paper_old']}/note").status_code == 204
    assert admin.put(f"/api/v1/items/{uuid4()}/note", json={"body": "x"}).status_code == 404


# ── highlights ───────────────────────────────────────────────────────


def highlight(c, item_id, quote="cut memory", field="abstract", **extra):
    start = ABSTRACT.find(quote) if field == "abstract" else None
    body = {"field": field, "quote": quote, "start": start,
            "prefix": ABSTRACT[max(0, start - 32):start] if start is not None else None,
            "suffix": ABSTRACT[start + len(quote):start + len(quote) + 32] if start is not None else None} | extra
    return c.post(f"/api/v1/items/{item_id}/highlights", json=body)


def test_highlights_belong_to_their_maker(env):
    admin, bo, ids, _ = env
    made = highlight(admin, ids["lora"], comment="the point")
    assert made.status_code == 201
    h = made.json()
    assert h["anchor"] == {"start": ABSTRACT.find("cut memory"), "end": ABSTRACT.find("cut memory") + 10}
    assert [x["quote"] for x in me(admin, ids["lora"])["highlights"]] == ["cut memory"]
    assert me(bo, ids["lora"])["highlights"] == []
    assert bo.patch(f"/api/v1/highlights/{h['id']}", json={"comment": "mine"}).status_code == 404
    assert bo.delete(f"/api/v1/highlights/{h['id']}").status_code == 404
    assert admin.patch(f"/api/v1/highlights/{h['id']}", json={"comment": " "}).json()["comment"] is None
    assert admin.delete(f"/api/v1/highlights/{h['id']}").status_code == 204
    assert me(admin, ids["lora"])["highlights"] == []


def test_highlights_go_in_text_the_app_shows(env):
    admin, _, ids, _ = env
    assert highlight(admin, ids["lora"], "Small", field="takeaway:0").status_code == 201
    assert highlight(admin, ids["lora"], "Fast", field="takeaway:5").status_code == 422
    assert highlight(admin, ids["lora"], "x", field="full_text").status_code == 422
    assert highlight(admin, ids["lora"], "   ", field="summary").status_code == 422
    passage = admin.post(f"/api/v1/evolution/papers/{ids['paper_old']}/highlights", json={
        "field": "passage", "quote": "a passage an answer cited", "context": {"topic": "peft", "section": "method"}})
    assert passage.status_code == 201 and passage.json()["anchor"] is None  # passages aren't marked in place
    assert admin.post(f"/api/v1/evolution/papers/{ids['paper_old']}/highlights",
                      json={"field": "summary", "quote": "x"}).status_code == 422


def test_a_highlight_follows_its_text_and_detaches_when_it_is_gone(env):
    admin, _, ids, Session = env
    highlight(admin, ids["lora"], "adapters")  # the second "adapters" in the abstract
    with Session() as s:
        item = s.get(ContentItem, ids["lora"])
        item.abstract = "Intro. " + ABSTRACT
        s.commit()
    moved = me(admin, ids["lora"])["highlights"][0]["anchor"]
    assert moved["start"] == len("Intro. ") + ABSTRACT.find("adapters")
    with Session() as s:
        s.get(ContentItem, ids["lora"]).abstract = "Something else entirely."
        s.commit()
    assert me(admin, ids["lora"])["highlights"][0]["anchor"] is None


def test_anchor_picks_the_match_with_the_closest_surroundings():
    text = "adapters here; then more adapters there"
    second = text.rfind("adapters")
    assert anchor(text, "adapters", 3, "then more ", " there") == {"start": second, "end": second + 8}
    assert anchor(text, "adapters", 0, None, None) == {"start": 0, "end": 8}
    assert anchor(text, "missing", 0, None, None) is None
    assert anchor(None, "adapters", 0, None, None) is None


# ── library ──────────────────────────────────────────────────────────


def test_library_lists_notes_and_highlights_per_paper(env):
    admin, bo, ids, _ = env
    admin.put(f"/api/v1/items/{ids['lora']}/note", json={"body": "Read with DoRA"})
    highlight(admin, ids["lora"])
    admin.put(f"/api/v1/evolution/papers/{ids['paper_old']}/note", json={"body": "Seminal"})
    entries = admin.get("/api/v1/library/notes").json()["entries"]
    assert {e["about"]["title"] for e in entries} == {"LORA", "paper_old"}
    lora = next(e for e in entries if e["about"]["kind"] == "item")
    assert lora["note"]["body"] == "Read with DoRA" and [h["quote"] for h in lora["highlights"]] == ["cut memory"]
    paper = next(e for e in entries if e["about"]["kind"] == "paper")
    assert paper["about"]["map"] == {"slug": "peft", "name": "PEFT"}
    assert [e["about"]["title"] for e in admin.get("/api/v1/library/notes?kind=paper").json()["entries"]] == \
        ["paper_old"]
    assert [e["about"]["title"] for e in admin.get("/api/v1/library/notes?q=memory").json()["entries"]] == ["LORA"]
    assert bo.get("/api/v1/library/notes").json()["entries"] == []


def test_read_history_counts_a_paper_read_in_both_places_once(env):
    admin, _, ids, _ = env
    admin.put(f"/api/v1/items/{ids['lora']}/read")       # also ticks paper_lora
    admin.put(f"/api/v1/evolution/papers/{ids['paper_old']}/read")
    history = admin.get("/api/v1/library/read").json()
    assert sorted(e["about"]["title"] for e in history["entries"]) == ["LORA", "paper_old"]
    assert history["pagination"]["total"] == 2
