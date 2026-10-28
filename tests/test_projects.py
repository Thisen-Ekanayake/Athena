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
    AppSetting, Artifact, ArtifactVersion, ChatMessage, ContentCategory, ContentItem, Conversation, ConversationMap,
    EvoIdeaCheck, EvoTopicPaper,
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
    assert models["qwen3.5-9b"] == {"id": "qwen3.5-9b", "reasoning": True, "vision": False, "tools": True,
                                    "context": 20480, "loaded": True}
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
    book = {"id": "1", "filename": "book.txt", "kind": "text", "text": "word " * 20000}
    t = turn(attachments=[book], files=[book])
    text, notices = chat.files_block(t, 2000)
    assert "File book.txt" in text and "[…cut to fit]" in text
    assert notices and "book.txt" in notices[0]
    content = chat.user_content(t, [{"n": 1, "title": "LoRA", "kind": "paper", "text": "Adapters."}], {})
    assert content.startswith("Passages from the project") and "[1] LoRA (paper)" in content
    assert content.endswith("Why?") and "word" not in content


def test_earlier_images_go_in_as_their_caption():
    fig = {"id": "f", "filename": "fig.png", "kind": "image", "caption": "A loss curve falling."}
    old = {"id": "g", "filename": "old.png", "kind": "image", "caption": None}
    text, _ = chat.files_block(turn(files=[fig, old]), 2000)
    assert "Image fig.png (as the vision model described it): A loss curve falling." in text
    assert "Image old.png: not described yet" in text
    text, _ = chat.files_block(turn(files=[fig], attachments=[fig]), 2000)
    assert text == ""  # this message's image goes in as an image


def test_shared_maps_shrink_to_fit_and_open_maps_are_one_line():
    from tests.test_evolution_digest import data
    t = turn(shared_maps=[{"key": "A", "data": data()}], open_maps=["Diffusion (diffusion)"])
    roomy = chat.system_prompt(t, 100_000)
    assert "Map A: PEFT [slug peft]" in roomy and "A4 fixes A1: “adapters" in roomy and "LoRA (A3)" in roomy
    assert "open beside the chat" in roomy and "Diffusion (diffusion)" in roomy
    tight = chat.system_prompt(t, 600)
    assert "Map A: PEFT" in tight and "“adapters" not in tight
    assert chat.digest_mentions("LoRA (A4) improves on Adapters (A1).", t) == {
        "A4": {"slug": "peft", "map": "PEFT", "paper_id": "p4", "label": "LoRA", "year": 2021},
        "A1": {"slug": "peft", "map": "PEFT", "paper_id": "p1", "label": "Adapters", "year": 2019}}
    assert chat.digest_mentions("A4", turn()) == {}


def test_the_system_prompt_carries_project_instructions():
    text = chat.system_prompt(turn(project_id=uuid4(), project_name="Thesis", catalog=["- Paper: LoRA"],
                                   instructions="Use British spelling.",
                                   artifacts=[{"id": "a1", "title": "Draft", "chars": 10}]))
    assert 'project "Thesis"' in text and "- Paper: LoRA" in text and "Use British spelling." in text
    assert "Draft (id a1" in text


def test_the_system_prompt_does_not_list_every_map():
    text = chat.system_prompt(turn())
    assert "query_map" in text and "PEFT" not in text


def test_made_up_citations_are_dropped():
    assert chat.drop_unknown_citations("Search papers [1]. Done [3].", 0) == "Search papers. Done."
    assert chat.drop_unknown_citations("LoRA [1][2] and DoRA [3].", 2) == "LoRA [1][2] and DoRA."
    assert chat.drop_unknown_citations("Use `x[1]` or\n```\na[2]\n```\nsee [docs](u) [1](u)", 0) == \
        "Use `x[1]` or\n```\na[2]\n```\nsee [docs](u) [1](u)"


# ── routes ───────────────────────────────────────────────────────────


pytestmark_api = pytest.mark.real_auth


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, AppSetting, UsageEvent, Source, ContentItem, EvoTopic, EvoPaper, EvoTopicPaper,
                  EvoIdeaCheck,
                  LitReview, SavedList, SavedListItem, Project, ProjectItem, Conversation, ConversationMap,
                  ChatMessage, UserFile, Artifact, ArtifactVersion):
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
    from athena.api.routers import chats as chats_router
    monkeypatch.setattr(chats_router, "_caption_images", lambda ids, model: None)  # no vision model here
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
        s.execute(EvoTopic.__table__.insert().values(id=uuid4(), slug="diffusion", name="Diffusion", status="building",
                                                     aliases=None, seeds=None, config=None, built_at=None))
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
def test_chats_pin_first_and_archived_leave_the_lists(env):
    admin, bo, ids, Session, queued = env
    first, second, third = (admin.post("/api/v1/chats", json={}).json()["id"] for _ in range(3))

    def listed(query=""):
        return [c["id"] for c in admin.get(f"/api/v1/chats{query}").json()["chats"]]

    pinned = admin.patch(f"/api/v1/chats/{first}", json={"pinned": True}).json()
    assert pinned["pinned"] is True and pinned["archived"] is False
    assert listed()[0] == first
    archived = admin.patch(f"/api/v1/chats/{second}", json={"archived": True}).json()
    assert archived["archived"] is True
    assert second not in listed() and listed("?archived=true") == [second]

    archived = admin.patch(f"/api/v1/chats/{first}", json={"archived": True}).json()
    assert archived["pinned"] is False  # archiving unpins
    back = admin.patch(f"/api/v1/chats/{first}", json={"archived": False}).json()
    assert back["archived"] is False and back["pinned"] is False
    assert set(listed()) == {first, third}
    assert bo.patch(f"/api/v1/chats/{third}", json={"pinned": True}).status_code == 404


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
    monkeypatch.setattr(llm, "async_chat_client", lambda **kw: model)
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
    assert done["stats"]["context_used"] == 160 and done["stats"]["context"] == 20480  # the last call's prompt + answer
    assert done["artifacts"][0]["title"] == "Draft"

    first = model.calls[0]
    assert first["extra_body"]["reasoning_budget_tokens"] == 4096 and first["tools"]
    assert "PEFT" not in first["messages"][0]["content"]
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
    monkeypatch.setattr(llm, "async_chat_client", lambda **kw: Down())
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


@pytestmark_api
def test_an_unknown_map_lists_the_maps(env):
    from athena.projects import tools
    ctx = tools.Context(user_id=uuid4(), project_id=None, conversation_id=uuid4(), message_id=None)
    text, info = tools.execute(ctx, "query_map", {"map": "transformers", "aspect": "gaps"})
    assert not info["ok"] and "- PEFT (peft)" in text
    assert info["summary"] == "no map called 'transformers'"   # the step shown on the page stays short


def test_searches_are_capped_and_papers_keep_their_numbers(monkeypatch):
    from athena.projects import tools
    from athena.search import arxiv_live, local, semantic_scholar
    found = [{"id": "s2a", "title": "DoRA", "abstract": "Weight-decomposed.", "url": "https://x/dora", "year": 2024,
              "authors": ["S. Liu"], "citation_count": 9, "source": "semantic_scholar"}]
    asked = []
    monkeypatch.setattr(local, "search_local", lambda q, limit: asked.append(limit) or [])
    monkeypatch.setattr(semantic_scholar, "search_semantic_scholar", lambda q, limit: found)
    monkeypatch.setattr(arxiv_live, "search_arxiv", lambda q, limit: [])
    ctx = tools.Context(user_id=uuid4(), project_id=None, conversation_id=uuid4(), message_id=None)
    ctx.add_source({"kind": "paper", "title": "LoRA", "link": "/items/1"})
    text, info = tools.execute(ctx, "search_papers", {"query": "dora"})
    assert info["ok"] and "[2] DoRA (2024)" in text and asked == [tools.LOCAL_RESULTS]
    text, info = tools.execute(ctx, "search_papers", {"query": "DoRA weight decomposed"})
    assert "[2] DoRA" in text and len(ctx.sources) == 2   # found again: same number
    text, info = tools.execute(ctx, "search_papers", {"query": "DoRA 2024"})
    assert not info["ok"] and "searched enough" in text


def test_off_topic_library_hits_are_left_out(monkeypatch):
    from athena.projects import tools
    from athena.search import arxiv_live, local, semantic_scholar
    hit = {"abstract": "", "url": "", "year": 2025, "authors": [], "source": "local"}
    monkeypatch.setattr(local, "search_local", lambda q, limit: [
        hit | {"id": "a", "title": "Lehmer's problem", "score": 0.49},
        hit | {"id": "b", "title": "Sinhala NER", "score": 0.66},
        hit | {"id": "c", "title": "HelaBERT for Sinhala", "score": 0.0}])  # a keyword hit: the title matches
    monkeypatch.setattr(semantic_scholar, "search_semantic_scholar", lambda q, limit: [])
    monkeypatch.setattr(arxiv_live, "search_arxiv", lambda q, limit: [])
    ctx = tools.Context(user_id=uuid4(), project_id=None, conversation_id=uuid4(), message_id=None)
    text, info = tools.execute(ctx, "search_papers", {"query": "HelaBERT"})
    assert [r["title"] for r in info["results"]] == ["Sinhala NER", "HelaBERT for Sinhala"]


def _registry_row(name: str, vision: bool) -> dict:
    plan = {"device": "gpu", "gpu_layers": 33, "layers": 33, "vram_mb": 5000, "ram_mb": 0, "fits": True}
    contexts = [{"context": c, "plan": plan, "server": "gpu",
                 "preset": name if c == 8192 else f"{name}@{c // 1024}k",
                 "vision_preset": (f"{name}-vision" if c == 8192 else f"{name}@{c // 1024}k-vision") if vision
                 else None} for c in (8192, 32768)]
    return {"id": name, "name": name, "role": "chat", "enabled": True, "reasoning": False, "vision": vision,
            "tools": True, "default_context": 8192, "contexts": contexts, "info": {}, "size_bytes": 1,
            "placement": "auto", "path": "x", "mmproj_path": None, "fingerprint": "", "options": {}, "layers": 33}


@pytestmark_api
def test_a_text_only_model_refuses_images_and_the_context_is_kept(env, monkeypatch, model_registry):
    admin, bo, ids, Session, queued = env
    model_registry += [_registry_row("tiny", vision=False), _registry_row("seer", vision=True)]
    monkeypatch.setattr(llm, "_cpu_models", lambda: [])
    picked = {m["id"]: m for m in admin.get("/api/v1/chat/models").json()["models"]}
    assert picked["tiny"]["vision"] is False and [c["tokens"] for c in picked["tiny"]["contexts"]] == [8192, 32768]
    c = admin.post("/api/v1/chats", json={"model": "tiny"}).json()
    fig = admin.post(f"/api/v1/chats/{c['id']}/files", files=[("files", ("fig.png", b"\x89PNG fake", "image/png"))])
    fid = fig.json()["files"][0]["id"]
    refused = admin.post(f"/api/v1/chats/{c['id']}/messages", json={
        "content": "What is this?", "model": "tiny", "attachment_ids": [fid]})
    assert refused.status_code == 422 and "reads text only" in refused.json()["detail"]

    sent = {}

    async def run(turn, *args, **kwargs):
        sent.update(model=chat.plan(turn)["model"], context=turn.context)
        yield {"type": "done", "message": {"content": "A figure."}}
    monkeypatch.setattr(chat, "run", run)
    monkeypatch.setattr(chat, "title_for", lambda q, a, m: None)
    ok = admin.post(f"/api/v1/chats/{c['id']}/messages", json={
        "content": "What is this?", "model": "seer", "context": 32768, "attachment_ids": [fid]})
    assert ok.status_code == 200 and sent == {"model": "seer@32k-vision", "context": 32768}
    assert admin.get(f"/api/v1/chats/{c['id']}").json()["context"] == 32768


# ── files and maps stay with the chat ────────────────────────────────


class Answerer:
    """Answers in one call, naming two map papers by id; records what it was sent."""

    def __init__(self, answer="LoRA (A4) fixed a limitation of Adapters (A1)."):
        self.calls, self.answer = [], answer
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = [chunk(content=self.answer), chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))]

        async def stream():
            for c in chunks:
                yield c
        return stream()

    @property
    def system(self) -> str:
        return self.calls[-1]["messages"][0]["content"]


@pytest.fixture
def answerer(monkeypatch):
    model = Answerer()
    monkeypatch.setattr(llm, "async_chat_client", lambda **kw: model)
    monkeypatch.setattr(llm, "model_context", lambda m: 20480)
    monkeypatch.setattr(chat, "title_for", lambda q, a, m: None)
    return model


@pytestmark_api
def test_files_stay_with_every_turn_until_taken_out(env, answerer):
    admin, bo, ids, Session, queued = env
    c = admin.post("/api/v1/chats", json={}).json()
    notes = admin.post(f"/api/v1/chats/{c['id']}/files", files=[
        ("files", ("notes.md", b"# Notes\nAdapters are cheap.", "text/markdown"))]).json()["files"][0]
    admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Read this", "attachment_ids": [notes["id"]]})
    assert "Adapters are cheap." in answerer.system
    assert answerer.calls[-1]["messages"][-1] == {"role": "user", "content": "Read this"}
    admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "And now?"})
    assert "File notes.md" in answerer.system and "Adapters are cheap." in answerer.system

    assert bo.patch(f"/api/v1/chats/{c['id']}/files/{notes['id']}", json={"detached": True}).status_code == 404
    r = admin.patch(f"/api/v1/chats/{c['id']}/files/{notes['id']}", json={"detached": True})
    assert r.status_code == 200 and r.json()["detached"] is True
    admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Still there?"})
    assert "Adapters are cheap." not in answerer.system
    view = admin.get(f"/api/v1/chats/{c['id']}").json()
    assert view["files"][0]["detached"] is True
    assert view["messages"][0]["attachments"][0]["filename"] == "notes.md"  # the message still shows it


@pytestmark_api
def test_maps_in_a_chat_are_shown_or_shared_as_graphs(env, answerer, monkeypatch):
    from athena.evolution import digest
    from tests.test_evolution_digest import data
    admin, bo, ids, Session, queued = env
    monkeypatch.setattr(digest, "digest", lambda session, topic: data() if topic.built_at else None)
    c = admin.post("/api/v1/chats", json={}).json()
    url = f"/api/v1/chats/{c['id']}/maps"
    assert admin.post(url, json={"maps": [{"id": "diffusion"}]}).status_code == 422  # not built
    assert admin.post(url, json={"maps": [{"id": "nope"}]}).status_code == 404
    assert bo.post(url, json={"maps": [{"id": "peft"}]}).status_code == 404
    maps = admin.post(url, json={"maps": [{"id": "peft"}]}).json()["maps"]
    assert [(m["slug"], m["key"], m["share"]) for m in maps] == [("peft", "A", False)]
    assert admin.get(f"/api/v1/chats/{c['id']}").json()["maps"][0]["name"] == "PEFT"

    got = events(admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Hi"}))
    done = next(e for e in got if e["type"] == "done")
    assert "open beside the chat" in answerer.system and "PEFT (peft)" in answerer.system
    assert "Map A:" not in answerer.system and done["message"]["map_refs"] == {}

    assert admin.patch(f"{url}/peft", json={"share": True}).json()["maps"][0]["share"] is True
    got = events(admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "How did PEFT develop?"}))
    assert "Map A: PEFT [slug peft]" in answerer.system and "A4 fixes A1" in answerer.system
    assert "open beside the chat" not in answerer.system
    refs = next(e for e in got if e["type"] == "done")["message"]["map_refs"]
    assert set(refs) == {"A4", "A1"} and refs["A4"]["paper_id"] == "p4"
    assert admin.get(f"/api/v1/chats/{c['id']}").json()["messages"][-1]["map_refs"]["A1"]["label"] == "Adapters"

    seen = admin.get(f"{url}/{ids['topic']}/digest").json()
    assert seen["key"] == "A" and seen["level"] in digest.LEVELS
    assert seen["levels"]["full"]["text"].startswith("Map A: PEFT") and seen["levels"]["minimal"]["tokens"] > 0
    assert admin.delete(f"{url}/peft").status_code == 204
    assert admin.get(f"/api/v1/chats/{c['id']}").json()["maps"] == []
    assert admin.delete(f"{url}/peft").status_code == 404


@pytestmark_api
def test_a_projects_shared_map_goes_to_its_chats(env, answerer, monkeypatch):
    from athena.evolution import digest
    from tests.test_evolution_digest import data
    admin, bo, ids, Session, queued = env
    monkeypatch.setattr(digest, "digest", lambda session, topic: data())
    pid = admin.post("/api/v1/projects", json={"name": "Thesis"}).json()["id"]
    item = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "map", "id": "peft"}).json()
    paper = admin.post(f"/api/v1/projects/{pid}/items", json={"kind": "paper", "id": str(ids["lora"])}).json()
    assert item["share"] is False and item["slug"] == "peft"
    assert admin.patch(f"/api/v1/projects/{pid}/items/{paper['id']}", json={"share": True}).status_code == 404
    assert bo.patch(f"/api/v1/projects/{pid}/items/{item['id']}", json={"share": True}).status_code == 404
    assert admin.patch(f"/api/v1/projects/{pid}/items/{item['id']}", json={"share": True}).json()["share"] is True

    c = admin.post("/api/v1/chats", json={"project_id": pid}).json()
    admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Hi"})
    assert "Map A: PEFT" in answerer.system
    # attached to the chat as well: one graph, with the chat's letter
    admin.post(f"/api/v1/chats/{c['id']}/maps", json={"maps": [{"id": "peft", "share": True}]})
    admin.post(f"/api/v1/chats/{c['id']}/messages", json={"content": "Again"})
    assert answerer.system.count("[slug peft]") == 1
