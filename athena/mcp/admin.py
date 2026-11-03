"""
Running Athena (admin accounts): what the GPU, queues and syncs are doing, starting a sync, pausing background
model work, and usage. For an agent working on Athena itself as much as for one using it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.mcp import common

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


async def _maybe(ctx: Context, path: str, **params):
    """A part of the status this account may not see (not an admin) is left out, not an error."""
    try:
        return await common.get(ctx, path, **params)
    except ToolError as exc:
        return {"unavailable": str(exc)}


def _when(epoch) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return "?"


def sync_text(s: dict) -> str:
    if "unavailable" in s:
        return f"Sync: {s['unavailable']}"
    if not s or not s.get("state"):
        return "Sync: none has run yet."
    head = (f"Sync ({s.get('trigger') or 'manual'}): {s['state']}, "
            f"{s.get('completed', 0)}/{s.get('total', 0)} sources, {s.get('new_items', 0)} new items, "
            f"{s.get('errors', 0)} errors; started {_when(s.get('started_at'))}"
            + (f", finished {_when(s['finished_at'])}" if s.get("finished_at") else "")
            + (" (waiting for the worker)" if s.get("waiting_for_worker") else ""))
    busy = [x for x in s.get("sources") or []
            if x.get("new") or x.get("state") not in ("done", None) or x.get("error")]
    lines = [head] + [f"- {x.get('name')}: {x.get('state')}" + (f", {x['new']} new" if x.get("new") else "")
                      + (f", error: {common.clip(x['error'], 160)}" if x.get("error") else "") for x in busy]
    return "\n".join(lines)


def activity_text(a: dict) -> str:
    if "unavailable" in a:
        return "Model activity: admins only."
    lane = a.get("lane") or {}
    lines = ["Model activity:"]
    for s in a.get("servers") or []:
        models = ", ".join(f"{m.get('preset')} ({m.get('status')}, {m.get('device') or '?'})"
                           for m in s.get("models") or []) or "nothing loaded"
        lines.append(f"- {s.get('server')} server {'online' if s.get('online') else 'OFFLINE'}: {models}")
    gpu = a.get("gpu") or {}
    if gpu:
        lines.append(f"- GPU: {common.compact(gpu, width=80).replace(chr(10), '; ')}")
    calls = a.get("calls") or []
    lines.append(f"- running calls: {len(calls)}" + "".join(
        f"\n    {c.get('label') or c.get('feature')} on {c.get('model')} ({c.get('user') or 'background'})"
        for c in calls[:10]))
    if lane.get("paused"):
        lines.append(f"- background work PAUSED: {common.compact(lane['paused'], width=80).replace(chr(10), '; ')}")
    if lane.get("turn"):
        lines.append(f"- GPU turn: {common.compact(lane['turn'], width=80).replace(chr(10), '; ')}")
    waiting = lane.get("waiting") or []
    if waiting:
        lines.append("- waiting: " + "; ".join(f"{w.get('label')} ({w.get('reason')})" for w in waiting[:10]))
    queues = [q for q in a.get("queues") or [] if q.get("count")]
    if queues:
        lines.append("- queued: " + "; ".join(f"{q['label']} {q['count']}" for q in queues))
    today = a.get("today")
    if today:
        lines.append(f"- today: {common.compact(today, width=80).replace(chr(10), '; ')}")
    return "\n".join(lines)


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, READ)
    async def athena_status(ctx: Context) -> str:
        """How Athena is doing: the sync of its sources, the model servers and GPU (what is loaded, running and
        waiting, whether background work is paused), its queues, and the scoring and fetch health. Most of it is
        for admin accounts."""
        sync = await _maybe(ctx, "/sync/status")
        activity = await _maybe(ctx, "/models/activity")
        scoring = await _maybe(ctx, "/health/scoring")
        fetch = await _maybe(ctx, "/health/fetch")
        parts = [sync_text(sync),
                 activity_text(activity),
                 "Scoring health:\n" + common.compact(scoring, width=160, items=12),
                 "Fetch health:\n" + common.compact(fetch, width=160, items=20)]
        return "\n\n".join(parts)

    @common.tool(mcp, WRITE)
    async def start_sync(ctx: Context) -> str:
        """Start a sync: crawl every active source for new items (admin). athena_status shows its progress."""
        started = await common.post(ctx, "/sync")
        return "Sync started.\n" + common.compact(started or {}, width=160)

    @common.tool(mcp, WRITE)
    async def pause_background(ctx: Context, group: Literal["feed", "maps"] | None = None) -> str:
        """Pause Athena's background model work (admin): summaries, labels and feed embeddings ("feed"), the maps'
        work ("maps"), or both. Chats, reviews and other asked-for work go on. resume_background ends it."""
        result = await common.post(ctx, "/models/activity/pause", {"group": group})
        return "Paused.\n" + common.compact(result or {}, width=160)

    @common.tool(mcp, WRITE)
    async def resume_background(ctx: Context, group: Literal["feed", "maps"] | None = None) -> str:
        """Resume background model work paused with pause_background (admin)."""
        result = await common.post(ctx, "/models/activity/resume", {"group": group})
        return "Resumed.\n" + common.compact(result or {}, width=160)

    @common.tool(mcp, READ)
    async def usage(ctx: Context, scope: Literal["me", "everyone"] = "me", days: int | None = None) -> str:
        """Model usage: this account's (tokens, cost, today's allowances) or everyone's (admin), by feature."""
        if scope == "me":
            return common.compact(await common.get(ctx, "/usage/me"), width=160, items=30)
        return common.compact(await common.get(ctx, "/usage/summary", days=days), width=160, items=30)
