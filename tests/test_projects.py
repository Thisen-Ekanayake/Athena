"""Projects and chats: effort and model listing, passages, fitting a turn into the context, the routes, privacy,
artifacts with versions, uploads, and a streamed turn with a fake model that thinks and writes an artifact."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core import llm
from athena.core.models import (
    AppSetting, Artifact, ArtifactVersion, ChatMessage, ContentCategory, ContentItem, Conversation, EvoIdeaCheck,
    EvoPaper, EvoTopic, LitReview, Project, ProjectItem, SavedList, SavedListItem, Source, SourceCategory,
    SourceType, UsageEvent, User, UserFile, UserSession,
)
from athena.projects import chat, index
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin


# ── effort and models ────────────────────────────────────────────────


@pytest.fixture
def settings(monkeypatch):
    values: dict[str, str] = {}
    monkeypatch.setattr(llm, "get_setting", lambda key, default="": values.get(key, default))
    monkeypatch.setattr(llm, "_models_cache", None)
    return values


def test_effort_is_a_thinking_budget_on_llama_cpp(settings):
    extra, budget = llm.effort_extra("qwen3.5-9b", "medium")
    assert budget == 4096
    assert extra["chat_template_kwargs"] == {"enable_thinking": True}
    assert extra["reasoning_budget_tokens"] == 4096 and "reasoning_budget_message" in extra
    assert llm.effort_extra("qwen3.5-9b", "off") == ({"chat_template_kwargs": {"enable_thinking": False}}, 0)


def test_a_model_that_does_not_reason_never_thinks(settings):
    settings.update(CHAT_REASONING_MODELS="big-thinker, other")
    assert llm.effort_extra("qwen3.5-9b", "high") == ({"chat_template_kwargs": {"enable_thinking": False}}, 0)
    assert llm.effort_extra("other", "high")[1] == 8192


def test_a_hosted_api_gets_reasoning_effort(settings):
    settings.update(LLM_BASE_URL="https://api.openai.com/v1", CHAT_REASONING_MODELS="o4")
    assert llm.effort_extra("o4", "low") == ({"reasoning_effort": "low"}, 1024)
    assert llm.effort_extra("o4", "off") == ({}, 0)


def test_the_router_lists_chat_models_without_embedder_or_vision(settings, monkeypatch):
    preset = "[qwen3.5-9b]\nmodel = models/x.gguf\nctx-size = 20480\n"
    monkeypatch.setattr(llm, "_server_models", lambda: [
        {"id": "qwen3.5-9b", "status": {"value": "loaded", "preset": preset}},
        {"id": "qwen3-embedding-8b", "status": {"value": "unloaded"}},
        {"id": "qwen3.5-9b-vision", "status": {"value": "unloaded"}},
        {"id": "gemma-4b", "status": {"value": "unloaded"},
         "architecture": {"input_modalities": ["text", "image"]}},
    ])
    models = {m["id"]: m for m in llm.chat_models()}
    assert set(models) == {"qwen3.5-9b", "gemma-4b"}
    assert models["qwen3.5-9b"] == {"id": "qwen3.5-9b", "reasoning": True, "vision": False, "context": 20480,
                                    "loaded": True}
    assert models["gemma-4b"]["reasoning"] is False and models["gemma-4b"]["vision"] is True
    assert models["gemma-4b"]["context"] == llm.DEFAULT_CONTEXT
    assert llm.model_context("qwen3.5-9b") == 20480


def test_no_listing_falls_back_to_the_configured_models(settings, monkeypatch):
    monkeypatch.setattr(llm, "_server_models", lambda: [])
    assert [m["id"] for m in llm.chat_models()] == ["qwen3.5-9b"]


# ── passages and fitting ─────────────────────────────────────────────


def test_chunks_break_at_paragraphs_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(8))
    chunks = index.chunk(text, size=1000, overlap=100)
    assert len(chunks) > 3
    assert all(len(c) <= 1000 for c in chunks)
    assert chunks[0].startswith("Paragraph 0.")
    assert index.chunk("short") == ["short"] and index.chunk("  ") == []


def turn(**fields) -> chat.Turn:
    base = dict(user_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(), project_id=None, project_name=None,
                project_description="", instructions="", catalog=[], artifacts=[], history=[], question="Why?",
                attachments=[], model="qwen3.5-9b", effort="high", first_turn=True)
    return chat.Turn(**(base | fields))


def test_a_small_context_thinks_less(settings, monkeypatch):
    monkeypatch.setattr(llm, "model_context", lambda model: 20480)
    plan = chat.plan(turn())
    assert plan["budget"] == 8192 and plan["max_tokens"] == 8192 + chat.ANSWER_TOKENS
    monkeypatch.setattr(llm, "model_context", lambda model: 12000)
    plan = chat.plan(turn())
    assert plan["budget"] == 12000 - chat.ANSWER_TOKENS - 256 - chat.MIN_PROMPT_TOKENS
    assert plan["extra"]["reasoning_budget_tokens"] == plan["budget"]
    assert plan["prompt_budget"] >= chat.MIN_PROMPT_TOKENS
    monkeypatch.setattr(llm, "model_context", lambda model: 7000)
    assert chat.plan(turn())["budget"] == 0


def test_images_go_to_the_vision_model(settings, monkeypatch):
    monkeypatch.setattr(llm, "model_context", lambda model: 12288)
    t = turn(attachments=[{"id": "1", "filename": "fig.png", "kind": "image", "path": "x", "mime": "image/png"}])
    assert chat.plan(t)["model"] == "qwen3.5-9b-vision"


def test_history_keeps_the_latest_turns_that_fit():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 300}
               for i in range(10)]
    kept = chat.fit_history(history, budget=400)
    assert kept and kept[0]["role"] == "user" and kept[-1]["content"].startswith("turn 9")
    assert len(kept) < 10


def test_long_files_are_cut_and_said_so():
    t = turn(attachments=[{"id": "1", "filename": "book.txt", "kind": "text", "text": "word " * 20000}])
    content, notices = chat.user_content(t, [{"n": 1, "title": "LoRA", "kind": "paper", "text": "Adapters."}], 2000,
                                         {})
    assert "[1] LoRA (paper)" in content and "[…cut to fit]" in content and content.endswith("Why?")
    assert notices and "book.txt" in notices[0]


def test_the_system_prompt_carries_project_instructions():
    text = chat.system_prompt(turn(project_id=uuid4(), project_name="Thesis", catalog=["- Paper: LoRA"],
                                   instructions="Use British spelling.",
                                   artifacts=[{"id": "a1", "title": "Draft", "chars": 10}]))
    assert 'project "Thesis"' in text and "- Paper: LoRA" in text and "Use British spelling." in text
    assert "Draft (id a1" in text


# ── routes ───────────────────────────────────────────────────────────


pytestmark_api = pytest.mark.real_auth


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, AppSetting, UsageEvent, Source, ContentItem, EvoTopic, EvoPaper, EvoIdeaCheck,
                  LitReview, SavedList, SavedListItem, Project, ProjectItem, Conversation, ChatMessage, UserFile,
                  Artifact, ArtifactVersion):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    import athena.database.db as dbmod
    from athena.projects import tasks
    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    queued = []
    monkeypatch.setattr(tasks, "queue", lambda pid: queued.append(str(pid)))
    monkeypatch.setattr(index, "delete_source", lambda source, qdrant=None: None)
    monkeypatch.setattr(index, "delete_project", lambda pid, qdrant=None: None)
    monkeypatch.setenv("ATHENA_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(llm, "_server_models", lambda: [])
    redis = FakeRedis()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    ids = {}
    with Session() as s:
        source_id = uuid4()
        s.execute(Source.__table__.insert().values(id=source_id, name="ArXiv AI", url="https://export.arxiv.org",
                                                   type=SourceType.API, category=SourceCategory.PAPER,
                                                   fetch_config=None))
        ids["lora"] = uuid4()
        s.execute(ContentItem.__table__.insert().values(
            id=ids["lora"], source_id=source_id, title="LoRA", url="http://arxiv.org/abs/lora",
            published_at=datetime(2021, 6, 1, tzinfo=timezone.utc), category=ContentCategory.PAPER,
            content_hash="lora", authors=["E. Hu"], extra_data={}, score=0.5, abstract="Low-rank adapters."))
        ids["topic"] = uuid4()
        s.execute(EvoTopic.__table__.insert().values(id=ids["topic"], slug="peft", name="PEFT", status="ready",
                                                     aliases=None, seeds=None, config=None,
                                                     built_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        s.commit()
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    _, bo = make_user(admin)
    yield admin, bo, ids, Session, queued
    app.dependency_overrides.clear()


@pytestmark_api
def test_a_project_gathers_things_and_stays_private(env):
    admin, bo, ids, Session, queued = env
    p = admin.post("/api/v1/projects", json={"name": "Thesis", "instructions": "Be brief."}).json()
    pid = p["id"]
    assert p["counts"] == {"chats": 0, "items": 0, "files": 0, "artifacts": 0}

    paper = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "paper", "id": str(ids["lora"])})
    assert paper.status_code == 201 and paper.json()["title"] == "LoRA" and paper.json()["link"].startswith("/items/")
    again = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "paper", "id": str(ids["lora"])}).json()
    assert again["created"] is False and again["id"] == paper.json()["id"]
    themap = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "map", "id": "peft"}).json()
    assert themap["title"] == "PEFT" and themap["slug"] == "peft"
    outside = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "paper", "meta": {
        "title": "DoRA", "year": 2024, "external_id": "s2:abc", "authors": ["S. Liu"]}}).json()
    assert outside["ref"] == "ext:s2:abc" and outside["subtitle"] == "S. Liu · 2024"
    assert queued == [pid] * 3

    assert admin.get(f"/api/v1/projects/membership?ref=item:{ids['lora']}").json()["project_ids"] == [pid]
    assert admin.get("/api/v1/projects/membership?ref=map:peft").json()["project_ids"] == [pid]

    full = admin.get(f"/api/v1/projects/{pid}").json()
    assert full["counts"]["items"] == 3 and {i["kind"] for i in full["items"]} == {"paper", "map"}

    # someone else's project is not there for them, nor can they add their things to it
    assert bo.get(f"/api/v1/projects/{pid}").status_code == 404
    assert bo.get("/api/v1/projects").json()["projects"] == []
    assert bo.post(f"/api/v1/projects/{pid}/items", json={"kind": "map", "id": "peft"}).status_code == 404
    with Session() as s:
        review = LitReview(user_id=s.execute(select(User.id).where(User.role != "admin")).scalar_one(),
                           title="Bo's review", mode="abstracts")
        s.add(review)
        s.commit()
        review_id = str(review.id)
    assert admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "review", "id": review_id}).status_code == 404

    assert admin.delete(f"/api/v1/projects/{pid}/items/{paper.json()['id']}").status_code == 204
    assert admin.patch(f"/api/v1/projects/{pid}", json={"name": "PhD"}).json()["name"] == "PhD"
    assert admin.delete(f"/api/v1/projects/{pid}").status_code == 204
    assert admin.get("/api/v1/projects").json()["projects"] == []
    with Session() as s:
        assert s.execute(select(ProjectItem)).first() is None


@pytestmark_api
def test_chats_move_between_projects_with_their_artifacts(env):
    admin, bo, ids, Session, queued = env
    pid = admin.post("/api/v1/projects", json={"name": "Thesis"}).json()["id"]
    c = admin.post("/api/v1/chats", json={}).json()
    assert c["title"] == "New chat" and c["project_id"] is None
    art = admin.post("/api/v1/artifacts", json={"title": "Notes", "content": "One", "chat_id": c["id"]}).json()
    assert art["project_id"] is None and art["index_status"] == "none"

    moved = admin.patch(f"/api/v1/chats/{c['id']}", json={"project_id": pid}).json()
    assert moved["project_id"] == pid and moved["project_name"] == "Thesis"
    assert admin.get(f"/api/v1/artifacts/{art['id']}").json()["project_id"] == pid
    assert [x["id"] for x in admin.get(f"/api/v1/chats?project_id={pid}").json()["chats"]] == [c["id"]]
    assert admin.get("/api/v1/chats?standalone=true").json()["chats"] == []

    out = admin.patch(f"/api/v1/chats/{c['id']}", json={"project_id": None}).json()
    assert out["project_id"] is None
    assert admin.patch(f"/api/v1/chats/{c['id']}", json={"title": "LoRA questions"}).json()["title"] == \
        "LoRA questions"
    assert bo.get(f"/api/v1/chats/{c['id']}").status_code == 404
    assert bo.patch(f"/api/v1/chats/{c['id']}", json={"title": "mine"}).status_code == 404
    assert admin.delete(f"/api/v1/chats/{c['id']}").status_code == 204
    assert admin.get(f"/api/v1/artifacts/{art['id']}").json()["conversation_id"] is None  # the artifact stays


@pytestmark_api
def test_artifacts_keep_every_version(env):
    admin, bo, ids, Session, queued = env
    a = admin.post("/api/v1/artifacts", json={"title": "Related work", "content": "## LoRA\nDraft."}).json()
    assert a["version"] == 1
    a = admin.patch(f"/api/v1/artifacts/{a['id']}", json={"content": "## LoRA\nBetter."}).json()
    assert a["version"] == 2
    same = admin.patch(f"/api/v1/artifacts/{a['id']}", json={"content": "## LoRA\nBetter."}).json()
    assert same["version"] == 2  # nothing changed, nothing saved
    versions = admin.get(f"/api/v1/artifacts/{a['id']}/versions").json()["versions"]
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["author"] == "user"
    assert admin.get(f"/api/v1/artifacts/{a['id']}/versions/1").json()["content"] == "## LoRA\nDraft."
    restored = admin.post(f"/api/v1/artifacts/{a['id']}/restore", json={"version": 1}).json()
    assert restored["version"] == 3 and restored["content"] == "## LoRA\nDraft."
    export = admin.get(f"/api/v1/artifacts/{a['id']}/export")
    assert export.text.startswith("# Related work") and "related-work.md" in export.headers["content-disposition"]
    assert bo.get(f"/api/v1/artifacts/{a['id']}").status_code == 404
    assert admin.delete(f"/api/v1/artifacts/{a['id']}").status_code == 204


@pytestmark_api
def test_uploads_are_read_into_text(env):
    admin, bo, ids, Session, queued = env
    pid = admin.post("/api/v1/projects", json={"name": "Thesis"}).json()["id"]
    r = admin.post(f"/api/v1/projects/{pid}/files", files=[
        ("files", ("notes.md", b"# Notes\nAdapters are cheap.", "text/markdown")),
        ("files", ("fig.png", b"\x89PNG fake", "image/png"))])
    assert r.status_code == 201
    notes, fig = r.json()["files"]
    assert notes["kind"] == "text" and notes["status"] == "ready" and notes["chars"] > 10
    assert notes["index_status"] == "pending" and fig["kind"] == "image" and fig["status"] == "ready"
    assert queued == [pid]
    assert admin.get(f"/api/v1/files/{notes['id']}/content").text.startswith("# Notes")
    assert bo.get(f"/api/v1/files/{notes['id']}/content").status_code == 404
    refused = admin.post(f"/api/v1/projects/{pid}/files", files=[("files", ("a.exe", b"MZ", "application/x-msdos"))])
    assert refused.status_code == 415
    assert admin.delete(f"/api/v1/files/{notes['id']}").status_code == 204
    assert admin.get(f"/api/v1/files/{notes['id']}/content").status_code == 404


# ── a streamed turn ──────────────────────────────────────────────────


def chunk(content=None, reasoning=None, tool=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=[tool] if tool else None, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)] if not usage else [], usage=usage)


def tool_call(name, arguments):
    return SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name=name, arguments=arguments))


class FakeModel:
    """Thinks, calls write_artifact, then answers; records what it was sent."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            chunks = [chunk(reasoning="The user wants a draft. "),
                      chunk(tool=tool_call("write_artifact", json.dumps({"title": "Draft", "content": "# Draft\n"}))),
                      chunk(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))]
        else:
            chunks = [chunk(content="I wrote a draft "), chunk(content="for you."),
                      chunk(usage=SimpleNamespace(prompt_tokens=150, completion_tokens=10))]

        async def stream():
            for c in chunks:
                yield c
        return stream()


def events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"]


@pytestmark_api
def test_a_turn_thinks_writes_an_artifact_and_is_saved(env, monkeypatch, usage_rows):
    admin, bo, ids, Session, queued = env
    model = FakeModel()
    monkeypatch.setattr(llm, "async_chat_client", lambda: model)
    monkeypatch.setattr(llm, "model_context", lambda m: 20480)
    monkeypatch.setattr(chat, "title_for", lambda q, a, m: "Drafting help")
    c = admin.post("/api/v1/chats", json={}).json()

    r = admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Draft me notes", "effort": "medium"})
    assert r.status_code == 200
    got = events(r)
    kinds = [e["type"] for e in got]
    assert kinds[0] == "start" and "reasoning" in kinds and "artifact" in kinds and kinds[-1] == "title"
    assert [e["step"]["status"] for e in got if e["type"] == "tool"] == ["running", "done"]
    done = next(e for e in got if e["type"] == "done")["message"]
    assert done["content"] == "I wrote a draft for you." and done["reasoning"] == "The user wants a draft. "
    assert done["status"] == "done" and done["effort"] == "medium"
    assert done["input_tokens"] == 250 and done["output_tokens"] == 30
    assert done["artifacts"][0]["title"] == "Draft"

    first = model.calls[0]
    assert first["extra_body"]["reasoning_budget_tokens"] == 4096 and first["tools"]
    assert first["messages"][-1] == {"role": "user", "content": "Draft me notes"}
    assert model.calls[1]["messages"][-1]["role"] == "tool"

    chat_view = admin.get(f"/api/v1/chats/{c['id']}").json()
    assert chat_view["title"] == "Drafting help" and chat_view["effort"] == "medium"
    assert [m["role"] for m in chat_view["messages"]] == ["user", "assistant"]
    assert chat_view["artifacts"][0]["title"] == "Draft"
    assert any(row["feature"] == "chat" for row in usage_rows)

    # again: the old answer goes, the question is answered anew, with the earlier turn as history
    model.calls.clear()
    r = admin.post(f"/api/v1/chats/{c['id']}/messages", json={"retry": True})
    assert [m["role"] for m in admin.get(f"/api/v1/chats/{c['id']}").json()["messages"]] == ["user", "assistant"]
    assert model.calls[0]["messages"][-1]["content"] == "Draft me notes"


@pytestmark_api
def test_a_failed_model_is_saved_as_failed(env, monkeypatch):
    admin, bo, ids, Session, queued = env

    class Down:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    async def refuse(**kwargs):
        raise ConnectionError("connection refused")
    Down.chat.completions.create = refuse
    monkeypatch.setattr(llm, "async_chat_client", lambda: Down())
    monkeypatch.setattr(chat, "title_for", lambda q, a, m: None)
    c = admin.post("/api/v1/chats", json={}).json()
    got = events(admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Hello there"}))
    assert any(e["type"] == "error" for e in got)
    done = next(e for e in got if e["type"] == "done")["message"]
    assert done["status"] == "failed" and "connection refused" in done["error"]
    assert admin.get(f"/api/v1/chats/{c['id']}").json()["title"] == "Hello there"


# ── indexing, retrieval and tools ────────────────────────────────────


class FakeQdrant:
    def __init__(self):
        self.points: dict[str, object] = {}

    def collection_exists(self, name):
        return True

    def upsert(self, name, points):
        for p in points:
            self.points[p.id] = p

    def delete(self, name, points_selector):
        source = points_selector.filter.must[0].match.value
        self.points = {k: p for k, p in self.points.items() if p.payload["source"] != source}

    def query_points(self, name, query, limit, with_payload, query_filter):
        wanted = query_filter.must[0].match.value
        hits = [SimpleNamespace(score=0.9 - i * 0.01, payload=p.payload)
                for i, p in enumerate(p for p in self.points.values() if p.payload["project_id"] == wanted)]
        return SimpleNamespace(points=hits[:limit])


@pytestmark_api
def test_a_project_is_indexed_and_searched(env, monkeypatch):
    import numpy as np
    admin, bo, ids, Session, queued = env
    pid = admin.post("/api/v1/projects", json={"name": "Thesis"}).json()["id"]
    admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "paper", "id": str(ids["lora"])})
    notes = ("notes.md", ("Adapters. " * 400).encode(), "text/markdown")
    admin.post(f"/api/v1/projects/{pid}/files", files=[("files", notes)])
    admin.post("/api/v1/artifacts", json={"title": "Plan", "content": "Read LoRA first.", "project_id": pid})
    qdrant = FakeQdrant()
    monkeypatch.setattr(index, "client", lambda: qdrant)
    monkeypatch.setattr(index, "ensure_collection", lambda q=None: None)
    monkeypatch.setattr(llm, "embed", lambda texts, **kw: np.ones((len(texts), 4), dtype=np.float32))
    from uuid import UUID
    with Session() as s:
        counts = index.index_pending(s, UUID(pid), full_text=False)
    assert counts == {"indexed": 3, "failed": 0}
    sources = {p.payload["source"].split(":")[0] for p in qdrant.points.values()}
    assert sources == {"item", "file", "artifact"}
    assert {i["index_status"] for i in admin.get(f"/api/v1/projects/{pid}").json()["items"]} == {"indexed"}

    found = index.retrieve(UUID(pid), "what are adapters?", limit=6, start=3)
    assert [p.n for p in found] == list(range(3, 3 + len(found)))
    per_source = {}
    for p in found:
        per_source[p.source] = per_source.get(p.source, 0) + 1
    assert max(per_source.values()) <= index.PER_SOURCE


@pytestmark_api
def test_edits_must_match_the_artifact(env):
    from uuid import UUID

    from athena.projects import tools
    admin, bo, ids, Session, queued = env
    a = admin.post("/api/v1/artifacts", json={"title": "Draft", "content": "LoRA is slow."}).json()
    user_id = UUID(admin.get("/api/v1/auth/me").json()["id"])
    ctx = tools.Context(user_id=user_id, project_id=None, conversation_id=uuid4(), message_id=None)
    text, info = tools.execute(ctx, "edit_artifact", {"artifact_id": a["id"], "edits": [
        {"find": "slow", "replace": "fast"}]})
    assert info["ok"] and "version 2" in text
    assert admin.get(f"/api/v1/artifacts/{a['id']}").json()["content"] == "LoRA is fast."
    text, info = tools.execute(ctx, "edit_artifact", {"artifact_id": a["id"], "edits": [
        {"find": "not there", "replace": "x"}]})
    assert not info["ok"] and "not found" in text
    text, info = tools.execute(ctx, "read_artifact", json.dumps({"artifact_id": str(uuid4())}))
    assert not info["ok"]
    bo_ctx = tools.Context(user_id=uuid4(), project_id=None, conversation_id=uuid4(), message_id=None)
    assert not tools.execute(bo_ctx, "read_artifact", {"artifact_id": a["id"]})[1]["ok"]  # not theirs
    assert tools.execute(ctx, "no_such_tool", {})[1]["ok"] is False
