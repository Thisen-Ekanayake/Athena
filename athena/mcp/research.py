"""
Research tasks: Athena does the work with its own pipeline and model, and hands back the finished result.

A review, a map's answer, an idea check, a new map, a chat turn: each is what the web app's button does, through the
same route, saved where the web app shows it. The agent passes the result on; it does not redo the research.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.mcp import common, lookup
from athena.mcp.api import ApiError

REFINE_WAIT = 120         # seconds a new map's proposal waits for Athena's model to check its anchor papers
BUILDING = ("pending", "building")
TASK = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


# ── reviews ──────────────────────────────────────────────────────────


def review_text(r: dict) -> str:
    grounded = (f"grounded in the map {r['topic']['name']} ({r['topic']['slug']})" if r.get("topic")
                else "written from search results' abstracts (no map covers this topic)")
    page = common.link(f"/reviews/{r['id']}")
    head = (f"# {r.get('title')}\n\nWritten by Athena ({r.get('model') or 'its model'}), {grounded}; "
            f"{r.get('cited', 0)} sources cited. Saved to the Reviews page: {page}\n"
            f"Review id: {r['id']} (my_reviews exports it as BibTeX)\n")
    return head + "\n" + (r.get("markdown") or "")


async def review_check(ctx: Context, review_id: str):
    async def check():
        r = await common.get(ctx, f"/reviews/{review_id}")
        if r["status"] == "failed":
            raise ToolError(f"Athena could not write the review: {r.get('error') or 'no reason given'}")
        p = r.get("progress") or {}
        return r["status"] == "done", p.get("step") or 0, p.get("of"), p.get("label") or r["status"]
    return check


async def wait_review(ctx: Context, review_id: str) -> str:
    try:
        await common.wait(ctx, f"review:{review_id}", await review_check(ctx, review_id))
    except common.StillRunning as exc:
        return common.still_running(exc, f"The review {review_id}")
    return review_text(await common.get(ctx, f"/reviews/{review_id}"))


# ── maps ─────────────────────────────────────────────────────────────


async def map_check(ctx: Context, slug: str):
    async def check():
        t = await common.get(ctx, f"/evolution/topics/{slug}")
        if t["status"] == "failed":
            raise ToolError(f"The map's build failed: {t.get('status_detail') or 'no reason given'}")
        return t["status"] not in BUILDING, 0, None, t.get("status_detail") or t["status"]
    return check


async def map_ready_text(ctx: Context, slug: str, built_now: bool) -> str:
    t = await common.get(ctx, f"/evolution/topics/{slug}")
    d = await common.get(ctx, f"/evolution/topics/{slug}/digest", level="compact")
    stats = t.get("build_stats") or {}
    lines = [f"{'Built' if built_now else 'Found'} the map {t['name']} (slug {slug}): "
             f"{stats.get('papers', '?')} papers. Open it: {common.link(f'/evolution/{slug}')}"]
    if t["status"] == "refining":
        lines.append("Athena is still improving it (reading full text, naming open problems); it can be read now.")
    lines += ["", d["text"], "",
              "Paper ids like A3 work with map_paper; map_details shows open problems, a reading path and more."]
    return "\n".join(lines)


async def wait_map(ctx: Context, slug: str, built_now: bool = False) -> str:
    try:
        await common.wait(ctx, f"map:{slug}", await map_check(ctx, slug))
    except common.StillRunning as exc:
        return common.still_running(exc, f"The build of the map {slug}")
    return await map_ready_text(ctx, slug, built_now)


def _new_topic(p: dict) -> dict:
    """What the web app sends when the proposal is built unchanged: the rules' picks, overridden by the model's."""
    refine = p.get("refine") or {}
    done = refine.get("status") == "done"
    pick = (lambda key: refine.get(key) if done and refine.get(key) is not None else p.get(key))
    candidates = {c["openalex_id"]: c for c in p.get("candidates") or []}
    return {"query": p["query"], "name": (done and refine.get("name")) or p["name"],
            "description": ((done and refine.get("description")) or p.get("description") or "")[:500],
            "aliases": pick("aliases") or [], "keywords": pick("keywords") or [],
            "anchors": [{"openalex_id": a, "alt_ids": candidates.get(a, {}).get("alt_ids", [])}
                        for a in pick("anchors") or []],
            "fields": p.get("fields") or [], "proposal_id": p["id"]}


# ── jobs ─────────────────────────────────────────────────────────────


async def wait_job(ctx: Context, job: str) -> str:
    kind, _, ident = job.partition(":")
    if not ident:
        raise ToolError("A job looks like review:<id> or map:<slug>, as the tool that started it said")
    if kind == "review":
        return await wait_review(ctx, ident)
    if kind == "map":
        return await wait_map(ctx, ident)
    raise ToolError(f"Unknown job kind {kind!r}: review or map")


# ── chat ─────────────────────────────────────────────────────────────


def chat_text(chat_id: str, message: dict, notices: list[str]) -> str:
    lines = [message.get("content") or "(no answer)"]
    if message.get("status") not in (None, "done"):
        lines.append(f"\n(The answer ended early: {message.get('error') or message.get('status')})")
    sources = message.get("sources") or []
    if sources:
        lines.append("\nSources:")
        for s in sources:
            where = s.get("map") and f", map {s['map']}" or ""
            lines.append(f"[{s.get('n')}] {s.get('title')}{where}" + (f" {s['link']}" if s.get("link") else ""))
    artifacts = message.get("artifacts") or []
    if artifacts:
        lines.append("\nArtifacts it wrote or changed (read_artifact reads them):")
        lines += [f"- {a.get('title')} (id {a.get('id')}, version {a.get('version')})" for a in artifacts]
    if notices:
        lines.append("\nNotes from Athena: " + " ".join(notices))
    lines.append(f"\nChat id {chat_id} (pass it as chat_id to go on): {common.link(f'/chats/{chat_id}')}")
    return "\n".join(lines)


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, TASK)
    async def literature_review(ctx: Context, query: str | None = None, map: str | None = None) -> str:
        """Have Athena write a literature review, with its own model, and return the finished review (Markdown with
        numbered citations and references). Give a topic as `query`, or name a research map as `map`. Athena grounds
        it in a map that covers the topic when there is one, else in search results' abstracts. Takes minutes:
        progress is reported. Present the review as Athena wrote it; do not research or rewrite it yourself unless
        the user asks."""
        if not query and not map:
            raise ToolError("Give a topic (query) or a map")
        body = {"query": query} if query else {}
        if map:
            body["topic_slug"] = (await lookup.find_map(ctx, map))["slug"]
        try:
            started = await common.call(ctx, "POST", "/reviews", body=body)
        except ToolError as exc:
            if "still being written" not in str(exc):
                raise
            mine = await common.get(ctx, "/reviews")
            busy = next((r for r in mine if r.get("status") in ("queued", "running")), None)
            if busy is None:
                raise
            await common.progress(ctx, 0, None, f"Waiting for your review already being written: {busy['title']}")
            return ("Another review of yours was still being written, so Athena finished that one first:\n\n"
                    + await wait_review(ctx, busy["id"]))
        return await wait_review(ctx, started["id"])

    @common.tool(mcp, TASK)
    async def ask_map(ctx: Context, map: str, question: str,
                      sections: list[Literal["method", "results", "limitations"]] | None = None) -> str:
        """Ask one of Athena's research maps a question. Athena finds passages in the map's papers and its model
        answers from them, citing [n]; the answer and its sources come back. `sections` limits the passages to
        those parts of the papers."""
        topic = await lookup.find_map(ctx, map)
        sources, parts, error = [], [], None
        await common.progress(ctx, 0, None, f"Searching the papers of {topic['name']}")
        try:
            async for event in common.api.stream(common.token(ctx), "POST",
                                                 f"/api/v1/evolution/topics/{topic['slug']}/ask",
                                                 body={"question": question, "sections": sections or []}):
                if "sources" in event:
                    sources = event["sources"]
                    await common.progress(ctx, 1, None, f"Writing the answer from {len(sources)} passages")
                elif "token" in event:
                    parts.append(event["token"])
                elif "error" in event:
                    error = event["error"]
        except ApiError as exc:
            raise common.refused(exc) from None
        if error and not parts:
            raise ToolError(error)
        lines = [f"Athena's answer from the map {topic['name']}:", "", "".join(parts).strip()]
        if sources:
            lines += ["", "Sources:"]
            for i, s in enumerate(sources, 1):
                where = "abstract" if s.get("abstract_only") else (s.get("heading") or s.get("section_type") or "")
                lines.append(f"[{s.get('n', i)}] {s.get('title')} ({s.get('year') or 'n.d.'})"
                             + (f", {where}" if where else "") + f": {common.clip(s.get('excerpt'), 200)}")
        lines.append(f"\nThe map: {common.link('/evolution/' + topic['slug'])}")
        return "\n".join(lines)

    @common.tool(mcp, TASK)
    async def check_idea(ctx: Context, idea: str) -> str:
        """Check a research idea against every research map in Athena: the closest published papers, the open
        problems it touches, and Athena's verdict on what is new. Describe the idea in a few sentences (20+
        characters). Takes up to a minute."""
        await common.progress(ctx, 0, None, "Comparing the idea with the maps' papers and open problems")
        check = await common.post(ctx, "/evolution/idea-checks", {"idea": idea, "verdict": True})
        result = check.get("result") or {}
        lines = [f"Idea check {check.get('id')}: {common.link('/evolution/ideas')}"]
        verdict = result.get("verdict") or {}
        for key, label in (("closest", "Closest work"), ("new", "What is new"), ("gaps", "Open problems")):
            if verdict.get(key):
                lines.append(f"\n{label}: {verdict[key]}")
        papers = result.get("papers") or []
        if papers:
            lines.append("\nMost similar papers:")
            for p in papers[:8]:
                maps = ", ".join(m.get("topic_name") or "" for m in p.get("maps") or [])
                lines.append(f"- {p.get('title')} ({p.get('year') or 'n.d.'}), {common.authors(p.get('authors'))}"
                             + (f"; in {maps}" if maps else "") + (f"; {p['url']}" if p.get("url") else ""))
        themes = result.get("themes") or []
        if themes:
            lines.append("\nOpen problems it touches:")
            lines += [f"- {t.get('label')} ({t.get('topic_name')}; "
                      f"{'still open' if t.get('open') else t.get('status')})" for t in themes[:8]]
        return "\n".join(lines)

    @common.tool(mcp, TASK)
    async def build_map(ctx: Context, query: str) -> str:
        """Have Athena build a research map for a field or topic: its papers, milestones, lineage and open problems.
        Returns the existing map when one already covers the query. A new map takes Athena many minutes (it
        gathers hundreds of papers and reads them); progress is reported, and if it takes longer than the wait you
        get a job for wait_for."""
        found = await common.get(ctx, "/evolution/search", q=query)
        if found.get("found"):
            topic = found["topic"]
            if topic["status"] in BUILDING:
                return await wait_map(ctx, topic["slug"])
            if topic["status"] in lookup.READABLE:
                return await map_ready_text(ctx, topic["slug"], built_now=False)
        await common.progress(ctx, 0, None, "Finding the field's key papers on OpenAlex")
        proposal = await common.post(ctx, "/evolution/proposals", {"query": query})
        if not proposal.get("candidates"):
            raise ToolError(f"OpenAlex found no papers for {query!r}; try another wording or the field's usual name")

        async def refined():
            nonlocal proposal
            proposal = await common.get(ctx, f"/evolution/proposals/{proposal['id']}")
            status = (proposal.get("refine") or {}).get("status")
            return status not in ("pending", "running"), 0, None, "Athena's model is checking the anchor papers"
        try:
            await common.wait(ctx, "", refined, seconds=REFINE_WAIT)
        except common.StillRunning:
            pass  # the rules' proposal stands, as in the web app
        topic = await common.post(ctx, "/evolution/topics", _new_topic(proposal))
        return await wait_map(ctx, topic["slug"], built_now=True)

    @common.tool(mcp, TASK)
    async def wait_for(ctx: Context, job: str) -> str:
        """Wait again for work a tool started and handed back as a job ("review:<id>" or "map:<slug>"), and return
        its result when it is done."""
        return await wait_job(ctx, job.strip())

    @common.tool(mcp, TASK)
    async def chat(ctx: Context, message: str, project: str | None = None, chat_id: str | None = None,
                   effort: Literal["off", "low", "medium", "high"] | None = None) -> str:
        """Talk to Athena's own chat model, as in its Chats page: it searches papers, asks maps and writes artifacts
        itself, and cites its sources. Name a `project` to work inside it (its papers, maps, files and
        instructions), or pass `chat_id` to go on with a chat. `effort` is how long it thinks (default low). The
        answer, its sources and any artifacts come back."""
        if chat_id:
            c = await common.get(ctx, f"/chats/{chat_id}")
        else:
            project_id = (await lookup.find_project(ctx, project))["id"] if project else None
            c = await common.post(ctx, "/chats", {"project_id": project_id, "effort": effort})
        chat_id = c["id"]
        done, notices, error, steps = None, [], None, 0
        try:
            async for event in common.api.stream(common.token(ctx), "POST", f"/api/v1/chats/{chat_id}/messages",
                                                 body={"content": message, "effort": effort}):
                kind = event.get("type")
                if kind == "loading":
                    state = event.get("state") or {}
                    await common.progress(ctx, steps, None, state.get("label") or "Loading the model")
                elif kind == "reasoning" and steps == 0:
                    steps = 1
                    await common.progress(ctx, steps, None, "Thinking")
                elif kind == "tool":
                    step = event.get("step") or {}
                    if step.get("status") == "running":
                        steps += 1
                        await common.progress(ctx, steps, None, step.get("label") or step.get("tool") or "A tool")
                elif kind == "token" and steps < 100:
                    steps = 100
                    await common.progress(ctx, steps, None, "Writing the answer")
                elif kind == "notice":
                    notices.append(event.get("text") or "")
                elif kind == "error":
                    error = event.get("message")
                elif kind == "done":
                    done = event.get("message") or {}
        except ApiError as exc:
            raise common.refused(exc) from None
        if done is None:
            raise ToolError(f"The chat did not answer: {error or 'no reason given'}")
        return chat_text(chat_id, done, notices)
