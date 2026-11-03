"""
Reading Athena's research maps: a field's papers, its lineage (main path), milestones, eras, open problems, people
and changes. Building a map and asking one a question are research tasks (athena.mcp.research).
"""
from __future__ import annotations

import re
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.mcp import common, lookup

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
PAPER_REF = re.compile(r"^[A-Z]\d+$")


def gaps_text(name: str, data: dict) -> str:
    themes = data.get("themes") or []
    lines = [f"Open problems in {name} ({len(themes)} themes, from the limitations its papers state):"]
    for t in themes[:20]:
        years = f"{t.get('first_year') or '?'}–{t.get('last_year') or '?'}"
        lines.append(f"- {t.get('label')} [{t.get('status')}, {years}, {t.get('size') or '?'} statements]")
        for e in (t.get("examples") or [])[:2]:
            p = e.get("stated_by") or e.get("paper") or {}
            lines.append(f"    “{common.clip(e.get('sentence'), 220)}” ({common.clip(p.get('title'), 70)}, "
                         f"{p.get('year') or 'n.d.'})")
        fixed = [f"{common.clip(p.get('named_method') or p.get('title'), 50)} ({p.get('year')})"
                 for p in (t.get("fixed_by") or [])[:3]]
        if fixed:
            lines.append(f"    addressed by: {'; '.join(fixed)}")
    progress = data.get("progress") or {}
    if progress and progress.get("stage") not in (None, "done"):
        lines.append(f"\n(Athena is still working on them: {progress.get('label') or progress.get('stage')})")
    return "\n".join(lines)


def reading_text(name: str, data: dict) -> str:
    steps = ([data["survey"]] if data.get("survey") else []) + (data.get("steps") or [])
    lines = [f"Reading path for {name}, in order:"]
    for i, s in enumerate(steps, 1):
        lines.append(f"{i}. {_name(s)}"
                     + (" [read]" if s.get("read") else "") + (f" — {s['why']}" if s.get("why") else ""))
    return "\n".join(lines)


def _name(n: dict) -> str:
    label, title = n.get("named_method") or "", n.get("title") or ""
    named = label and not title.lower().startswith(label.lower())
    return f"{label + ': ' if named else ''}{common.clip(title, 90)} ({n.get('year') or 'n.d.'})"


def paper_text(p: dict, page: str) -> str:
    """A map paper: what it is, its place in the lineage, the citing sentences that link it, its limitations."""
    flags = [x for x, on in (("milestone", p.get("is_milestone")), ("on the main path", p.get("on_main_path"))) if on]
    about = [common.authors(p.get("authors")), p.get("venue") or "", f"{p.get('cited_by_count') or 0} citations",
             *flags]
    lines = [f"# {_name(p)}", "; ".join(x for x in about if x),
             " ".join(x for x in (p.get("url"), p.get("doi") and f"doi:{p['doi']}") if x), f"In Athena: {page}"]
    if p.get("abstract"):
        lines += ["", common.clip(p["abstract"], 1200)]
    for key, title in (("builds_on", "Builds on"), ("built_upon_by", "Built upon by")):
        if p.get(key):
            lines += ["", f"{title}:"] + [f"- {_name(n)}" for n in p[key][:6]]
    for key, title in (("addresses", "Takes on limitations of"), ("addressed_by", "Its limitations taken on by")):
        if p.get(key):
            lines += ["", f"{title}:"]
            for x in p[key][:6]:
                said = next((e.get("sentence") for e in x.get("evidence") or [] if e.get("sentence")), None)
                lines.append(f"- {_name(x.get('paper') or {})}" + (f": “{common.clip(said, 220)}”" if said else ""))
    if p.get("gaps"):
        lines += ["", "Limitations stated:"]
        for g in p["gaps"][:8]:
            by = g.get("stated_by")
            lines.append(f"- “{common.clip(g.get('sentence'), 220)}”" + (f" [{g['theme']}]" if g.get("theme") else "")
                         + (f" (said by {_name(by)})" if by else ""))
    return "\n".join(lines)


VIEWS = {
    "gaps": ("/gaps", {}),
    "reading_path": ("/reading-path", {}),
    "changes": ("/changes", {}),
    "people": ("/people", {}),
    "rising": ("/rising", {}),
    "timeline": ("/timeline", {}),
    "links": ("/links", {}),
}


async def paper_id(ctx: Context, slug: str, paper: str) -> str:
    """A paper id from the digest (A3) or the map's own id."""
    paper = paper.strip()
    if PAPER_REF.match(paper):
        refs = (await common.get(ctx, f"/evolution/topics/{slug}/digest", level="minimal"))["papers"]
        ref = refs.get("A" + paper[1:])
        if ref is None:
            raise ToolError(f"The map has no paper {paper}; map_overview lists its papers")
        return ref["paper_id"]
    return paper


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, READ)
    async def list_maps(ctx: Context) -> str:
        """Athena's research maps: each field's name, slug, size and state. Maps are shared by every account."""
        maps = await common.get(ctx, "/evolution/topics")
        if not maps:
            return "There are no maps yet; build_map makes one."
        lines = []
        for t in maps:
            stats = t.get("build_stats") or {}
            size = f"{t.get('paper_count') or stats.get('papers') or '?'} papers"
            state = t["status"] if t["status"] != "ready" else ""
            lines.append(f"- {t['name']} (slug {t['slug']}; {size}{'; ' + state if state else ''})"
                         + (f": {common.clip(t['description'], 160)}" if t.get("description") else ""))
        return "\n".join(lines)

    @common.tool(mcp, READ)
    async def map_overview(ctx: Context, map: str, detail: Literal["full", "compact", "minimal"] = "compact") -> str:
        """A research map as text: its milestone papers (ids like A3), the main path of the field's lineage, how
        papers build on or fix each other, its eras and open problems. The fastest way to understand a field."""
        topic = await lookup.find_map(ctx, map)
        d = await common.get(ctx, f"/evolution/topics/{topic['slug']}/digest", level=detail)
        return (d["text"] + f"\n\nOpen in Athena: {common.link('/evolution/' + topic['slug'])}. "
                "map_paper gives one paper (by its id, like A3); map_details gives more views.")

    @common.tool(mcp, READ)
    async def map_details(ctx: Context, map: str,
                          view: Literal["gaps", "reading_path", "changes", "people", "rising", "timeline", "links"]
                          ) -> str:
        """One view of a research map: "gaps" (open problems and whether later papers fixed them), "reading_path"
        (papers to read, in order), "changes" (what its latest refreshes added), "people" (key authors and
        groups), "rising" (its papers gaining citations), "timeline" (papers by year), "links" (related maps)."""
        topic = await lookup.find_map(ctx, map)
        path, params = VIEWS[view]
        data = await common.get(ctx, f"/evolution/topics/{topic['slug']}{path}", **params)
        if view == "gaps":
            return gaps_text(topic["name"], data)
        if view == "reading_path":
            return reading_text(topic["name"], data)
        return f"{view.replace('_', ' ').capitalize()} of {topic['name']}:\n" + common.compact(data, width=220)

    @common.tool(mcp, READ)
    async def map_paper(ctx: Context, map: str, paper: str) -> str:
        """One paper of a research map: why it matters there, what it cites and what cites it, how (from citing
        sentences), and its stated limitations. `paper` is an id from map_overview (like A3) or the paper's id."""
        topic = await lookup.find_map(ctx, map)
        pid = await paper_id(ctx, topic["slug"], paper)
        data = await common.get(ctx, f"/evolution/topics/{topic['slug']}/papers/{pid}")
        return paper_text(data, common.link(f"/evolution/{topic['slug']}"))
