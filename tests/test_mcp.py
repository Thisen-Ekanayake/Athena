"""The MCP server for agents (athena/mcp/): the in-process API client, the token check at /mcp, and the tools, which
hand Athena's finished work back (reviews, map answers, new maps, chat turns) through the web app's own routes."""
from __future__ import annotations

import asyncio

import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel

from athena.api import auth
from athena.api.config import settings
from athena.mcp import access, api, common, server
from athena.mcp.api import ApiError
from athena.mcp.server import mcp


# ── the in-process API client ────────────────────────────────────────


class Body(BaseModel):
    n: int


def tiny_app() -> tuple[FastAPI, dict]:
    app, seen = FastAPI(), {"closed": False}

    @app.get("/who")
    def who(request: Request, q: str | None = None):
        return {"agent": request.scope.get(auth.AGENT), "auth": request.headers.get("authorization"), "q": q}

    @app.post("/double")
    def double(body: Body):
        return {"n": body.n * 2}

    @app.get("/text")
    def text():
        return PlainTextResponse("@article{x}")

    @app.get("/missing")
    def missing():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Not now")

    @app.post("/events")
    async def events():
        async def gen():
            try:
                for i in range(50):
                    yield f"data: {{\"i\": {i}}}\n\n"
                    await asyncio.sleep(0.01)
                yield "data: [DONE]\n\n"
            finally:
                seen["closed"] = True
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app, seen


@pytest.fixture
def tiny(monkeypatch):
    app, seen = tiny_app()
    monkeypatch.setattr(api, "_app", app)
    return seen


async def test_a_call_goes_in_as_the_agent_with_its_token(tiny):
    got = await api.request("ath_t", "GET", "/who", params={"q": "lora", "skip": None})
    assert got == {"agent": True, "auth": "Bearer ath_t", "q": "lora"}
    assert await api.request("ath_t", "POST", "/double", body={"n": 21}) == {"n": 42}
    assert await api.request("ath_t", "GET", "/text") == "@article{x}"


async def test_refusals_carry_the_routes_detail(tiny):
    with pytest.raises(ApiError) as exc:
        await api.request("ath_t", "GET", "/missing")
    assert exc.value.status == 409 and exc.value.detail == "Not now"
    with pytest.raises(ApiError) as exc:
        await api.request("ath_t", "POST", "/double", body={"n": "many"})
    assert exc.value.status == 422 and "n:" in exc.value.detail


async def test_events_stream_and_leaving_early_stops_the_route(tiny):
    got = []
    async for event in api.stream("ath_t", "POST", "/events"):
        got.append(event["i"])
        if len(got) == 3:
            break
    assert got == [0, 1, 2]
    for _ in range(50):
        if tiny["closed"]:
            break
        await asyncio.sleep(0.01)
    assert tiny["closed"]  # the generator saw the client go


# ── the door ─────────────────────────────────────────────────────────


async def test_mcp_needs_a_valid_token(monkeypatch):
    monkeypatch.setattr(access, "valid", lambda token: token == "ath_good")
    async with server.running():
        transport = httpx2.ASGITransport(app=server.endpoint)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as http:
            r = await http.post("/mcp", json={})
            assert r.status_code == 401 and "Settings → Agents" in r.json()["error_description"]
            r = await http.post("/mcp", json={}, headers={"Authorization": "Bearer ath_bad"})
            assert r.status_code == 401


async def test_an_agent_connects_over_http_and_lists_the_tools(monkeypatch):
    monkeypatch.setattr(access, "valid", lambda token: token == "ath_good")
    async with server.running():
        transport = httpx2.ASGITransport(app=server.endpoint)
        http = httpx2.AsyncClient(transport=transport, headers={"Authorization": "Bearer ath_good"})
        async with Client(streamable_http_client("http://localhost:8000/mcp", http_client=http)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"literature_review", "ask_map", "build_map", "chat", "find_papers", "map_overview"} <= names
            assert "Athena does the work" in (c.instructions or "")


async def test_the_endpoint_is_closed_while_the_api_is_not_running():
    transport = httpx2.ASGITransport(app=server.endpoint)
    async with httpx2.AsyncClient(transport=transport, base_url="http://localhost") as http:
        assert (await http.post("/mcp", json={})).status_code == 503


# ── tools, against a fake API ────────────────────────────────────────


class FakeApi:
    """Routes by (method, path): a value, a function of (params, body), or a list answered in turn (the last one
    repeats). Streams are lists of events."""

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.calls: list[tuple] = []

    def on(self, method: str, path: str, answer) -> None:
        self.routes[(method, "/api/v1" + path)] = answer

    def _answer(self, method, path, params, body):
        self.calls.append((method, path.removeprefix("/api/v1"), params, body))
        if (method, path) not in self.routes:
            raise ApiError(404, f"no fake route {method} {path}")
        answer = self.routes[(method, path)]
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if callable(answer):
            answer = answer(params, body)
        if isinstance(answer, ApiError):
            raise answer
        return answer

    async def request(self, token, method, path, *, params=None, body=None):
        assert token == "ath_test"
        return self._answer(method, path, params, body)

    async def stream(self, token, method, path, *, body=None):
        for event in self._answer(method, path, None, body):
            yield event

    def sent(self, method: str, path: str) -> list:
        return [c[3] for c in self.calls if c[0] == method and c[1] == path]


@pytest.fixture
def fake(monkeypatch):
    f = FakeApi()
    monkeypatch.setattr(api, "request", f.request)
    monkeypatch.setattr(api, "stream", f.stream)
    monkeypatch.setattr(common, "token", lambda ctx: "ath_test")  # in memory there are no headers
    monkeypatch.setattr(common, "POLL_SECONDS", 0)
    monkeypatch.setattr(settings, "PUBLIC_URL", "http://athena.test")
    f.on("GET", "/evolution/topics", [[{"slug": "peft", "name": "PEFT", "aliases": ["parameter-efficient tuning"],
                                        "status": "ready", "status_detail": None, "build_stats": {"papers": 120}}]])
    return f


async def call(name: str, args: dict, progress: list | None = None) -> tuple[bool, str]:
    async def on_progress(step, total, message):
        progress.append(message)
    async with Client(mcp) as c:
        result = await c.call_tool(name, args, progress_callback=on_progress if progress is not None else None)
    return result.is_error, result.content[0].text


def review(status: str, **extra) -> dict:
    return {"id": "r1", "title": "PEFT: a literature review", "status": status, "mode": "map",
            "topic": {"slug": "peft", "name": "PEFT"}, "cited": 12, "model": "qwen3.5-9b",
            "progress": {"step": 2, "of": 5, "label": f"Writing ({status})"}} | extra


async def test_a_review_is_written_by_athena_and_returned_whole(fake):
    fake.on("POST", "/reviews", review("queued"))
    written = "## Overview\nAdapters [1]...\n\n## References\n[1] Houlsby"
    fake.on("GET", "/reviews/r1", [review("running"), review("running"), review("done", markdown=written)])
    progress = []
    failed, text = await call("literature_review", {"map": "parameter-efficient tuning"}, progress)
    assert not failed
    assert fake.sent("POST", "/reviews") == [{"topic_slug": "peft"}]
    assert "## References" in text and "http://athena.test/reviews/r1" in text and "grounded in the map PEFT" in text
    assert "Writing (running)" in progress


async def test_a_long_review_hands_back_a_job_to_wait_for(fake, monkeypatch):
    monkeypatch.setattr(settings, "MCP_WAIT_SECONDS", 0)
    fake.on("POST", "/reviews", review("queued"))
    fake.on("GET", "/reviews/r1", [review("running"), review("done", markdown="## Overview\nDone.")])
    failed, text = await call("literature_review", {"query": "lora"})
    assert not failed and 'job "review:r1"' in text
    monkeypatch.setattr(settings, "MCP_WAIT_SECONDS", 60)
    failed, text = await call("wait_for", {"job": "review:r1"})
    assert not failed and "Done." in text


async def test_a_second_review_waits_for_the_one_being_written(fake):
    fake.on("POST", "/reviews", ApiError(409, "A review of yours is still being written; wait for it to finish"))
    fake.on("GET", "/reviews", [[review("running")]])
    fake.on("GET", "/reviews/r1", review("done", markdown="Earlier review."))
    failed, text = await call("literature_review", {"query": "lora"})
    assert not failed and "finished that one first" in text and "Earlier review." in text


async def test_a_spent_allowance_is_an_error_the_agent_reads(fake):
    fake.on("POST", "/reviews", ApiError(429, "You have used today's 10 literature reviews."))
    failed, text = await call("literature_review", {"query": "lora"})
    assert failed and "Athena refused (429): You have used today's 10 literature reviews." in text


async def test_a_map_answers_with_its_sources(fake):
    fake.on("GET", "/evolution/search", {"found": False})
    fake.on("POST", "/evolution/topics/peft/ask", [[
        {"sources": [{"n": 1, "title": "LoRA", "year": 2021, "heading": "Method", "abstract_only": False,
                      "excerpt": "We freeze the weights"}]},
        {"token": "Low-rank updates "}, {"token": "[1]."}, {"done": True, "question_id": "q1"}]])
    failed, text = await call("ask_map", {"map": "PEFT", "question": "Why low rank?"})
    assert not failed
    assert "Low-rank updates [1]." in text and "[1] LoRA (2021), Method: We freeze the weights" in text


async def test_an_unknown_map_lists_the_maps(fake):
    fake.on("GET", "/evolution/search", {"found": False})
    failed, text = await call("map_overview", {"map": "protein folding"})
    assert failed and "PEFT (peft)" in text and "build_map" in text


async def test_a_new_map_is_proposed_built_and_returned(fake):
    fake.on("GET", "/evolution/search", {"found": False})
    proposal = {"id": "p1", "query": "graph transformers", "name": "Graph transformers", "description": "",
                "aliases": [], "fields": ["Computer Science"], "anchors": ["W1"], "keywords": ["graph"],
                "candidates": [{"openalex_id": "W1", "alt_ids": ["W9"]}, {"openalex_id": "W2", "alt_ids": []}]}
    fake.on("POST", "/evolution/proposals", proposal | {"refine": {"status": "pending"}})
    fake.on("GET", "/evolution/proposals/p1", [proposal | {"refine": {"status": "running"}},
                                               proposal | {"refine": {"status": "done", "name": "Graph Transformers",
                                                                      "anchors": ["W1", "W2"]}}])
    topic = {"slug": "graph-transformers", "name": "Graph Transformers", "status": "pending",
             "status_detail": "Waiting for the evolution worker", "build_stats": {}}
    fake.on("POST", "/evolution/topics", topic)
    fake.on("GET", "/evolution/topics/graph-transformers", [
        topic, topic | {"status": "building", "status_detail": "Fetching citations"},
        topic | {"status": "ready", "status_detail": None, "build_stats": {"papers": 300}}])
    fake.on("GET", "/evolution/topics/graph-transformers/digest", {"text": "Map A: Graph Transformers ...",
                                                                   "papers": {}})
    progress = []
    failed, text = await call("build_map", {"query": "graph transformers"}, progress)
    assert not failed
    sent = fake.sent("POST", "/evolution/topics")[0]
    assert sent["name"] == "Graph Transformers" and sent["proposal_id"] == "p1"
    assert sent["anchors"] == [{"openalex_id": "W1", "alt_ids": ["W9"]}, {"openalex_id": "W2", "alt_ids": []}]
    assert "Built the map Graph Transformers" in text and "300 papers" in text and "Map A:" in text
    assert "Fetching citations" in progress


async def test_an_existing_map_is_returned_not_built_again(fake):
    fake.on("GET", "/evolution/search", {"found": True, "topic": {"slug": "peft", "status": "ready"}})
    fake.on("GET", "/evolution/topics/peft", {"slug": "peft", "name": "PEFT", "status": "ready",
                                              "build_stats": {"papers": 120}})
    fake.on("GET", "/evolution/topics/peft/digest", {"text": "Map A: PEFT", "papers": {}})
    failed, text = await call("build_map", {"query": "parameter efficient fine tuning"})
    assert not failed and text.startswith("Found the map PEFT") and not fake.sent("POST", "/evolution/proposals")


async def test_a_map_paper_is_named_by_its_digest_id(fake):
    fake.on("GET", "/evolution/search", {"found": False})
    fake.on("GET", "/evolution/topics/peft/digest", {"text": "", "papers": {"A3": {"paper_id": "uuid-3"}}})
    fake.on("GET", "/evolution/topics/peft/papers/uuid-3", {"title": "LoRA", "year": 2021, "cites": []})
    failed, text = await call("map_paper", {"map": "peft", "paper": "A3"})
    assert not failed and "title: LoRA" in text


async def test_a_chat_turn_comes_back_with_sources_and_artifacts(fake):
    fake.on("GET", "/projects", {"projects": [{"id": "pr1", "name": "Thesis"}]})
    fake.on("POST", "/chats", {"id": "c1"})
    fake.on("POST", "/chats/c1/messages", [[
        {"type": "start", "message_id": "m1"},
        {"type": "tool", "step": {"tool": "search_papers", "label": "Searched for papers", "status": "running"}},
        {"type": "token", "text": "LoRA"},
        {"type": "done", "message": {"content": "LoRA adapts low-rank updates [1].", "status": "done",
                                     "sources": [{"n": 1, "title": "LoRA", "link": "/items/i1"}],
                                     "artifacts": [{"id": "a1", "title": "Notes", "version": 1}]}}]])
    progress = []
    failed, text = await call("chat", {"message": "What is LoRA?", "project": "thesis"}, progress)
    assert not failed
    assert fake.sent("POST", "/chats") == [{"project_id": "pr1", "effort": None}]
    assert "low-rank updates [1]" in text and "[1] LoRA" in text and "Notes (id a1" in text
    assert "Chat id c1" in text and "Searched for papers" in progress


async def test_an_artifact_passage_is_replaced(fake):
    fake.on("GET", "/artifacts/a1", {"id": "a1", "title": "Notes", "content": "LoRA is slow.", "version": 1})
    fake.on("PATCH", "/artifacts/a1", lambda params, body: {"title": "Notes", "version": 2, **body})
    failed, text = await call("edit_artifact", {"artifact_id": "a1", "find": "slow", "replace": "fast"})
    assert not failed and fake.sent("PATCH", "/artifacts/a1") == [{"content": "LoRA is fast."}]
    failed, text = await call("edit_artifact", {"artifact_id": "a1", "find": "missing", "replace": "x"})
    assert failed and "not in the artifact" in text


async def test_resources_and_prompts(fake):
    fake.on("GET", "/evolution/topics/peft/digest", {"text": "Map A: PEFT [slug peft]", "papers": {}})
    async with Client(mcp) as c:
        got = await c.read_resource("athena://maps/peft")
        assert got.contents[0].text == "Map A: PEFT [slug peft]"
        prompt = await c.get_prompt("lit_review", {"topic": "LoRA"})
        assert "literature_review" in prompt.messages[0].content.text


# ── end to end: a tool through the real routes, in the token's account ──


@pytest.mark.real_auth
async def test_a_tool_sees_what_its_tokens_account_sees(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from athena.api.deps import get_db, get_redis
    from athena.api.main import app
    from athena.core.models import ApiToken, ItemRead, SavedList, SavedListItem, User, UserSession
    from tests.test_auth import FakeRedis, make_user, setup_admin

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (User.__table__, UserSession.__table__, ApiToken.__table__, SavedList.__table__,
                  SavedListItem.__table__, ItemRead.__table__):
        table.create(engine)
    Session = sessionmaker(bind=engine)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        admin = TestClient(app)
        setup_admin(admin)
        admin.post("/api/v1/lists", json={"name": "To read"})
        _, bo = make_user(admin)
        bo.post("/api/v1/lists", json={"name": "Bo's list"})
        token = admin.post("/api/v1/tokens", json={"name": "agent"}).json()["token"]

        monkeypatch.setattr(api, "_app", app)
        monkeypatch.setattr(common, "token", lambda ctx: token)
        failed, text = await call("saved_lists", {})
        assert not failed and "To read" in text and "Bo's list" not in text

        monkeypatch.setattr(common, "token", lambda ctx: "ath_revoked")
        failed, text = await call("saved_lists", {})
        assert failed and "Athena refused (401)" in text and "Settings → Agents" in text
    finally:
        app.dependency_overrides.clear()
