"""
Tools the model may call during a chat: search for papers, ask a research map, and write, read or edit artifacts.

Each tool returns (text for the model, a summary for the page). Papers and map passages a tool finds join the
turn's numbered sources, so the answer can cite them as [n]. Search results are only offered: the user adds them
to the project with a click, never the model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID

from loguru import logger

SEARCH_RESULTS = 8
MAP_PASSAGES = 8
EXCERPT = 500

TOOLS = [
    {"type": "function", "function": {
        "name": "search_papers",
        "description": "Search for research papers: Athena's own library first, then Semantic Scholar and arXiv. "
                       "Use it when the user asks for papers, or about work the passages you were given do not "
                       "cover. The results are numbered sources you can cite as [n].",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A short search query, like a paper title or a topic"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "query_map",
        "description": "Ask one of Athena's research maps (a field's papers, milestones and open problems). "
                       "aspect 'answer' returns passages from the map's papers that answer the question (cite them "
                       "as [n]); 'gaps' lists the field's open problems; 'reading_path' lists papers to read in "
                       "order.",
        "parameters": {"type": "object", "properties": {
            "map": {"type": "string", "description": "The map's name or slug"},
            "question": {"type": "string"},
            "aspect": {"type": "string", "enum": ["answer", "gaps", "reading_path"]}},
            "required": ["map", "aspect"]}}},
    {"type": "function", "function": {
        "name": "write_artifact",
        "description": "Create a new document (an artifact) the user can open, edit and export: a draft, a "
                       "related-work section, a summary table, notes, a plan. Write the whole document in Markdown. "
                       "Use it when the user asks for something to keep, not for a short answer.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "The full document in Markdown"}},
            "required": ["title", "content"]}}},
    {"type": "function", "function": {
        "name": "read_artifact",
        "description": "Read the current text of an artifact, by its id, before changing it.",
        "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string"}},
                       "required": ["artifact_id"]}}},
    {"type": "function", "function": {
        "name": "edit_artifact",
        "description": "Change an artifact: give either 'content' (the whole new document) or 'edits' (exact "
                       "passages to find and what to put instead). Each find must match the current text exactly.",
        "parameters": {"type": "object", "properties": {
            "artifact_id": {"type": "string"},
            "title": {"type": "string", "description": "A new title, if it should change"},
            "content": {"type": "string"},
            "edits": {"type": "array", "items": {"type": "object", "properties": {
                "find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["find", "replace"]}}},
            "required": ["artifact_id"]}}},
]

LABELS = {"search_papers": "Searched for papers", "query_map": "Asked a map", "write_artifact": "Wrote an artifact",
          "read_artifact": "Read an artifact", "edit_artifact": "Edited an artifact"}


@dataclass
class Context:
    """What tools need about the turn, and what they add to it."""
    user_id: UUID
    project_id: UUID | None
    conversation_id: UUID
    message_id: UUID | None
    sources: list[dict] = field(default_factory=list)       # numbered, shared with retrieval
    artifacts: list[dict] = field(default_factory=list)     # written or changed this turn: [{id, title, version}]

    def add_source(self, source: dict) -> int:
        n = len(self.sources) + 1
        self.sources.append({"n": n} | source)
        return n


def execute(ctx: Context, name: str, raw_args: str | dict) -> tuple[str, dict]:
    """Run one tool call; errors go back to the model as text so it can try again."""
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return "Error: the arguments were not valid JSON.", {"ok": False, "summary": "Bad arguments"}
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Error: there is no tool called {name}.", {"ok": False, "summary": f"Unknown tool {name}"}
    try:
        return handler(ctx, args)
    except ToolError as exc:
        return f"Error: {exc}", {"ok": False, "summary": str(exc)}
    except Exception as exc:
        logger.warning(f"Chat tool {name} failed: {exc}")
        return f"Error: the tool failed ({str(exc)[:200]}).", {"ok": False, "summary": "The tool failed"}


class ToolError(Exception):
    pass


def _session():
    from athena.database.db import SessionLocal
    return SessionLocal()


# ── search ───────────────────────────────────────────────────────────


def search_papers(ctx: Context, args: dict) -> tuple[str, dict]:
    from athena.search.arxiv_live import search_arxiv
    from athena.search.local import search_local
    from athena.search.merger import merge_results
    from athena.search.semantic_scholar import search_semantic_scholar

    query = str(args.get("query") or "").strip()
    if len(query) < 2:
        raise ToolError("give a search query")
    local = search_local(query, limit=SEARCH_RESULTS)
    live = search_semantic_scholar(query, limit=10) + search_arxiv(query, limit=10)
    found = merge_results(local, live, max_total=SEARCH_RESULTS)
    in_project = _project_refs(ctx)
    results, lines = [], []
    for p in found:
        local_hit = p.get("source") == "local"
        ref = f"item:{p['id']}" if local_hit else None
        meta = None if local_hit else {
            "title": p.get("title"), "abstract": p.get("abstract"), "url": p.get("url"), "year": p.get("year"),
            "authors": (p.get("authors") or [])[:10], "external_id": p.get("id"), "source": p.get("source")}
        n = ctx.add_source({"kind": "paper", "title": p.get("title") or "", "link": f"/items/{p['id']}"
                            if local_hit else p.get("url"), "excerpt": (p.get("abstract") or "")[:400]})
        results.append({"n": n, "title": p.get("title"), "year": p.get("year"), "authors": (p.get("authors") or [])[:3],
                        "url": p.get("url"), "source": p.get("source"), "item_id": p["id"] if local_hit else None,
                        "meta": meta, "in_project": bool(ref and ref in in_project)})
        authors = ", ".join((p.get("authors") or [])[:3])
        lines.append(f"[{n}] {p.get('title')} ({p.get('year') or 'n.d.'}) {authors}\n"
                     f"{(p.get('abstract') or '')[:EXCERPT]}")
    text = "\n\n".join(lines) if lines else "No papers found."
    return text, {"ok": True, "summary": f"{len(results)} papers for “{query}”", "results": results}


def _project_refs(ctx: Context) -> set[str]:
    if not ctx.project_id:
        return set()
    from sqlalchemy import select

    from athena.core.models import ProjectItem
    with _session() as session:
        return set(session.execute(select(ProjectItem.ref).where(ProjectItem.project_id == ctx.project_id)).scalars())


# ── maps ─────────────────────────────────────────────────────────────


def _find_map(session, name: str):
    from sqlalchemy import func, select

    from athena.core.models import EvoTopic
    from athena.database import evolution as evo
    name = (name or "").strip()
    topic = evo.get_topic(session, name) or session.execute(
        select(EvoTopic).where(func.lower(EvoTopic.name) == name.lower())).scalars().first() \
        or evo.find_topic(session, name)
    if topic is None:
        raise ToolError(f"no map called {name!r}")
    if topic.built_at is None:
        raise ToolError(f"the map {topic.name} is not built yet")
    return topic


def query_map(ctx: Context, args: dict) -> tuple[str, dict]:
    from athena.database import evolution as evo
    from athena.evolution import ask

    aspect = args.get("aspect") or "answer"
    with _session() as session:
        topic = _find_map(session, str(args.get("map") or ""))
        if aspect == "gaps":
            themes = evo.topic_gaps(session, topic).get("themes", [])[:12]
            lines = [f"- {t['label']} ({t['status']}, {t.get('first_year')}–{t.get('last_year')})"
                     + (f": “{t['examples'][0]['sentence']}”" if t.get("examples") else "") for t in themes]
            return (f"Open problems in {topic.name}:\n" + ("\n".join(lines) or "none recorded"),
                    {"ok": True, "summary": f"{len(themes)} open problems in {topic.name}", "map": topic.slug})
        if aspect == "reading_path":
            path = evo.reading_path(session, topic, ctx.user_id, 8)
            steps = ([path["survey"]] if path.get("survey") else []) + path.get("steps", [])
            lines = [f"{i}. {s.get('named_method') or s['title']} ({s.get('year')}): {s['title']}"
                     + (f" — {s['why']}" if s.get("why") else "") for i, s in enumerate(steps, 1)]
            return (f"Reading path for {topic.name}:\n" + "\n".join(lines),
                    {"ok": True, "summary": f"Reading path for {topic.name}", "map": topic.slug})
        question = str(args.get("question") or "").strip()
        if len(question) < 3:
            raise ToolError("give a question for the map")
        try:
            found = ask.retrieve(session, topic, question, chunk_limit=MAP_PASSAGES)[:MAP_PASSAGES]
        except ask.AskUnavailable as exc:
            raise ToolError(str(exc))
    lines = []
    for s in found:
        where = "abstract" if s.abstract_only else f"{ask.SECTION_LABELS.get(s.section_type, 'Body')}: {s.heading}"
        n = ctx.add_source({"kind": "map", "title": f"{s.title} ({s.year or 'n.d.'})",
                            "link": f"/evolution/{topic.slug}", "excerpt": s.text[:400], "map": topic.name,
                            "section": where})
        lines.append(f"[{n}] {s.title} ({s.year or 'n.d.'}), {where}\n{s.text[:1200]}")
    return ("\n\n".join(lines) or f"The map {topic.name} has no passages about that.",
            {"ok": True, "summary": f"{len(found)} passages from {topic.name}", "map": topic.slug})


# ── artifacts ────────────────────────────────────────────────────────


def _own_artifact(session, ctx: Context, artifact_id: str):
    from athena.database import projects as db
    try:
        a = db.get_artifact(session, ctx.user_id, UUID(str(artifact_id)))
    except ValueError:
        a = None
    if a is None:
        raise ToolError(f"no artifact with id {artifact_id}")
    return a


def _note(ctx: Context, a) -> None:
    ctx.artifacts = [x for x in ctx.artifacts if x["id"] != str(a.id)] + [
        {"id": str(a.id), "title": a.title, "version": a.version}]


def write_artifact(ctx: Context, args: dict) -> tuple[str, dict]:
    from athena.database import projects as db
    title, content = str(args.get("title") or "").strip(), str(args.get("content") or "")
    if not content.strip():
        raise ToolError("the artifact needs content")
    with _session() as session:
        a = db.create_artifact(session, ctx.user_id, title or "Untitled", content, project_id=ctx.project_id,
                               conversation_id=ctx.conversation_id, message_id=ctx.message_id)
        _note(ctx, a)
        ref = {"id": str(a.id), "title": a.title, "version": a.version}
        return (f"Created artifact {a.id} titled {a.title!r} ({len(content)} characters). The user can see it.",
                {"ok": True, "summary": f"Wrote “{a.title}”", "artifact": ref})


def read_artifact(ctx: Context, args: dict) -> tuple[str, dict]:
    with _session() as session:
        a = _own_artifact(session, ctx, args.get("artifact_id"))
        ref = {"id": str(a.id), "title": a.title, "version": a.version}
        return f"# {a.title} (version {a.version})\n\n{a.content}", {"ok": True, "summary": f"Read “{a.title}”",
                                                                     "artifact": ref}


def edit_artifact(ctx: Context, args: dict) -> tuple[str, dict]:
    from athena.database import projects as db
    with _session() as session:
        a = _own_artifact(session, ctx, args.get("artifact_id"))
        content = args.get("content")
        if content is None and args.get("edits"):
            content, missing = a.content, []
            for edit in args["edits"]:
                find = str(edit.get("find") or "")
                if not find or find not in content:
                    missing.append(find[:80])
                    continue
                content = content.replace(find, str(edit.get("replace") or ""), 1)
            if missing:
                raise ToolError("these passages were not found, nothing was changed: "
                                + "; ".join(repr(m) for m in missing) + ". Read the artifact and try again.")
        if content is None and not args.get("title"):
            raise ToolError("give the new content, edits or a title")
        before = a.version
        a = db.revise_artifact(session, a, content=content, title=args.get("title"), message_id=ctx.message_id)
        _note(ctx, a)
        changed = a.version != before
        return (f"Artifact {a.id} is now version {a.version}." if changed else "Nothing changed.",
                {"ok": True, "summary": f"Edited “{a.title}”" if changed else f"“{a.title}” unchanged",
                 "artifact": {"id": str(a.id), "title": a.title, "version": a.version}})


HANDLERS = {"search_papers": search_papers, "query_map": query_map, "write_artifact": write_artifact,
            "read_artifact": read_artifact, "edit_artifact": edit_artifact}
