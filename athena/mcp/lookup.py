"""
Things an agent names loosely: a map by its name, slug or a topic it covers; a project or saved list by name or id.
"""
from __future__ import annotations

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from athena.mcp import common

READABLE = ("ready", "refining")  # a refining map can be read while it is improved


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


async def find_map(ctx: Context, name: str, *, built: bool = True) -> dict:
    """The map's summary. By slug, name or alias first, then the map whose papers match ``name``."""
    wanted = _norm(name)
    if not wanted:
        raise ToolError("Name a map (list_maps shows them)")
    maps = await common.get(ctx, "/evolution/topics")
    topic = next((t for t in maps if wanted in (_norm(t["slug"]), _norm(t["name"]))
                  or wanted in {_norm(a) for a in t.get("aliases") or []}), None)
    if topic is None:
        found = await common.get(ctx, "/evolution/search", q=name)
        topic = found.get("topic") if found.get("found") else None
    if topic is None:
        names = ", ".join(f"{t['name']} ({t['slug']})" for t in maps[:40]) or "none yet"
        raise ToolError(f"No map matches {name!r}. The maps: {names}. build_map makes a new one.")
    if built and topic.get("status") not in READABLE:
        detail = topic.get("status_detail") or "no detail"
        raise ToolError(f"The map {topic['name']} is {topic.get('status')} ({detail})"
                        f"; wait_for job \"map:{topic['slug']}\" waits for its build.")
    return topic


async def find_project(ctx: Context, name: str) -> dict:
    projects = (await common.get(ctx, "/projects"))["projects"]
    wanted = _norm(name)
    hit = next((p for p in projects if wanted in (_norm(str(p.get("id"))), _norm(p.get("name")))), None)
    if hit is None:
        names = ", ".join(p["name"] for p in projects[:40]) or "none yet"
        raise ToolError(f"No project of yours is called {name!r}. Your projects: {names}.")
    return hit


async def find_list(ctx: Context, name: str) -> dict:
    lists = await common.get(ctx, "/lists")
    wanted = _norm(name)
    hit = next((x for x in lists if wanted in (_norm(str(x.get("id"))), _norm(x.get("name")))), None)
    if hit is None:
        names = ", ".join(x["name"] for x in lists[:40]) or "none yet"
        raise ToolError(f"No saved list of yours is called {name!r}. Your lists: {names}.")
    return hit
