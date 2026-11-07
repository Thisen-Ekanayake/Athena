"""
Conference proceedings: the ACL family's editions (ACL, EMNLP, NAACL, EACL, AACL, COLING, TACL, CL) from the ACL
Anthology, sorted into a fixed topic list, with award winners, citation counts, rising terms and written summaries.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.mcp import common

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
Venue = Literal["all", "acl", "emnlp", "naacl", "eacl", "aacl", "coling", "tacl", "cl"]
Kind = Literal["main", "findings", "journal"]


def _kinds(kinds: list[Kind] | None) -> str | None:
    return ",".join(kinds) if kinds else None


def _pp(change: float | None) -> str:
    if change is None:
        return ""
    points = change * 100
    return f" ({'+' if points >= 0 else '−'}{abs(points):.1f} pts)"


def paper_line(p: dict, n: int | None = None) -> str:
    awards = f" [{'; '.join(p['awards'])}]" if p.get("awards") else ""
    cites = f", {p['citation_count']} citations" if p.get("citation_count") else ""
    topic = f", {p['topic']['name']}" if p.get("topic") else ""
    head = f"{f'{n}. ' if n else '- '}{p.get('title')} ({p.get('year')}{cites}{topic}){awards}"
    return f"{head}\n   {common.authors(p.get('authors'))} · id {p.get('id')} {p.get('url') or ''}".rstrip()


async def _topic_id(ctx: Context, name: str) -> tuple[int, str]:
    listing = await common.get(ctx, "/conferences")
    topics = listing.get("topics") or []
    wanted = name.strip().lower()
    match = next((t for t in topics if t["name"].lower() == wanted), None) or \
        next((t for t in topics if wanted in t["name"].lower()), None)
    if match is None:
        raise ToolError(f"No topic {name!r}. The topics: " + "; ".join(t["name"] for t in topics))
    return match["id"], match["name"]


def _page(venue: str, year: int | None = None) -> str:
    return common.link(f"/library/conferences/{venue}" + (f"?year={year}" if year else ""))


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, READ)
    async def conference_overview(ctx: Context, venue: Venue = "all", year: int | None = None,
                                  kinds: list[Kind] | None = None) -> str:
        """What one edition of an NLP conference was about, from the ACL Anthology: its papers' topic shares and how
        they moved since the previous edition, rising and falling terms, award-winning papers and Athena's summary.
        venue "all" is the whole ACL family's year; without a year, the latest edition. kinds picks main
        proceedings, Findings and/or journal papers (all by default)."""
        v = await common.get(ctx, f"/conferences/{venue}", year=year, kinds=_kinds(kinds))
        kinds_text = ", ".join(f"{n} {k}" for k, n in (v.get("by_kind") or {}).items())
        lines = [f"# {v['name']} {v['year']}: {v['papers']} papers ({kinds_text})",
                 f"Editions: {', '.join(str(y['year']) for y in v['years'][-12:])}; compared with "
                 f"{v.get('previous_year') or 'nothing (first edition)'}.", f"In Athena: {_page(venue, v['year'])}"]
        prog = v.get("progress") or {}
        if prog.get("papers") and prog.get("sorted", 0) < prog["papers"]:
            lines.append(f"Note: {prog['sorted']} of {prog['papers']} papers are sorted into topics so far.")
        if v.get("summary"):
            lines += ["", v["summary"]["text"]]
        lines += ["", "Topics (share of papers):"]
        lines += [f"- {t['name']}: {t['share'] * 100:.1f}% ({t['papers']}){_pp(t.get('change'))}"
                  for t in v["topics"] if t["papers"]][:15]
        terms = v.get("terms") or {}
        if terms.get("rising"):
            lines += ["", "Rising terms: " + ", ".join(t["term"] for t in terms["rising"][:15])]
        if terms.get("falling"):
            lines.append("Falling terms: " + ", ".join(t["term"] for t in terms["falling"][:10]))
        if v.get("awards"):
            lines += ["", "Award-winning papers:"] + [paper_line(p) for p in v["awards"][:12]]
        return "\n".join(lines)

    @common.tool(mcp, READ)
    async def conference_trends(ctx: Context, venue: Venue = "all", topics: list[str] | None = None,
                                start: int | None = None, end: int | None = None,
                                kinds: list[Kind] | None = None) -> str:
        """How topics' shares of an NLP venue's papers changed year by year (ACL Anthology, sorted into a fixed topic
        list). Name topics to follow (default: the six biggest in the last year). venue "all" is the whole ACL
        family."""
        t = await common.get(ctx, f"/conferences/{venue}/trends", kinds=_kinds(kinds), start=start, end=end)
        years = [y for y in t["years"] if y["sorted"]]
        if not years:
            return f"No {t['name']} papers are sorted into topics yet."
        names = {str(x["id"]): x["name"] for x in t["topics"]}
        if topics:
            chosen = []
            for name in topics:
                hit = next((k for k, n in names.items() if name.lower() in n.lower()), None)
                if hit is None:
                    raise ToolError(f"No topic {name!r}. The topics: " + "; ".join(names.values()))
                chosen.append(hit)
        else:
            last = years[-1]["topics"]
            chosen = sorted(last, key=lambda k: -last[k])[:6]
        lines = [f"# {t['name']}: share of papers per topic, {years[0]['year']}–{years[-1]['year']}", "",
                 "Year | papers | " + " | ".join(names[k] for k in chosen)]
        for y in years:
            lines.append(f"{y['year']} | {y['papers']} | " + " | ".join(
                f"{y['topics'].get(k, 0) / y['sorted'] * 100:.1f}%" for k in chosen))
        lines.append(f"\nIn Athena: {_page(venue)}")
        return "\n".join(lines)

    @common.tool(mcp, READ)
    async def compare_conferences(ctx: Context, venues: list[Venue], year: int,
                                  kinds: list[Kind] | None = None) -> str:
        """NLP venues side by side in one year: each one's papers and topic shares (ACL Anthology), e.g. ACL against
        EMNLP in 2025."""
        c = await common.get(ctx, "/conferences/compare", venues=",".join(venues), year=year, kinds=_kinds(kinds))
        if not c["venues"]:
            return f"None of {', '.join(venues)} has papers from {year}."
        names = {str(x["id"]): x["name"] for x in c["topics"]}
        total = {}
        for v in c["venues"]:
            for k, n in v["topics"].items():
                total[k] = total.get(k, 0) + n / max(v["sorted"], 1)
        order = sorted(total, key=lambda k: -total[k])[:15]
        lines = [f"# {year}: " + ", ".join(f"{v['name']} ({v['papers']} papers)" for v in c["venues"]), "",
                 "Topic | " + " | ".join(v["name"] for v in c["venues"])]
        for k in order:
            lines.append(f"{names.get(k, k)} | " + " | ".join(
                f"{v['topics'].get(k, 0) / max(v['sorted'], 1) * 100:.1f}%" for v in c["venues"]))
        if c.get("missing"):
            lines.append(f"\nNo {year} edition: {', '.join(c['missing'])}.")
        return "\n".join(lines)

    @common.tool(mcp, READ)
    async def conference_papers(ctx: Context, venue: Venue = "all", year: int | None = None,
                                topic: str | None = None, awards_only: bool = False,
                                kinds: list[Kind] | None = None, limit: int = 15) -> str:
        """The top papers of an NLP venue (ACL Anthology): award winners first, then by citations; in one year or
        across all years, in one topic or all of them. Ids work with Athena's conference pages; the links are the
        Anthology's."""
        topic_id, topic_name = await _topic_id(ctx, topic) if topic else (None, None)
        page = await common.get(ctx, f"/conferences/{venue}/papers", year=year, topic=topic_id,
                                kinds=_kinds(kinds), awards="true" if awards_only else None,
                                limit=max(1, min(limit, 50)))
        papers = page.get("papers") or []
        what = f"{page['name']} {year or 'all years'}" + (f", {topic_name}" if topic_name else "")
        if not papers:
            return f"No papers for {what}."
        return f"Top papers, {what} ({page['total']} in all):\n" + "\n".join(
            paper_line(p, n) for n, p in enumerate(papers, 1))
