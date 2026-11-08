"""
Finding papers: Athena's library and feed, and live search on Semantic Scholar and arXiv.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from athena.mcp import common

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
SORTS = {"relevance": "score", "recent": "date", "for_you": "foryou"}


def item_line(i: dict, n: int | None = None) -> str:
    """One feed item: title, where from, when, its id, and the start of its summary."""
    source = (i.get("source") or {}).get("name") or ""
    when = (i.get("published_at") or "")[:10]
    head = f"{f'{n}. ' if n else '- '}{i.get('title')} ({', '.join(x for x in (source, when) if x)})"
    extra = []
    if i.get("gain"):
        extra.append(f"+{i['gain']} citations")
    elif i.get("citation_count"):
        extra.append(f"{i['citation_count']} citations")
    if i.get("me", {}).get("saved") or i.get("me", {}).get("read"):
        extra.append("read" if i["me"].get("read") else "saved")
    lines = [head + (f" [{'; '.join(extra)}]" if extra else ""), f"   id {i.get('id')} {i.get('url') or ''}".rstrip()]
    if i.get("summary"):
        lines.append(f"   {common.clip(i['summary'], 260)}")
    return "\n".join(lines)


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, READ)
    async def find_papers(ctx: Context, query: str, limit: int = 15) -> str:
        """Search for research papers everywhere Athena looks: its own library (only papers close to the query),
        Semantic Scholar and arXiv, taken in turns by relevance and deduplicated; a title naming the query or a name
        in it ("HalOmi", "NLLB-200") comes first. Returns titles, years, authors, links and abstracts. Papers with an
        Athena id can be opened with get_paper, saved to lists and added to projects."""
        found = await common.post(ctx, "/search", {"query": query, "limit": max(1, min(limit, 50))})
        papers = found.get("papers") or []
        if not papers:
            return f"No papers found for {query!r}."
        lines = [f"{len(papers)} papers for {query!r} ({found.get('local_count', 0)} from Athena's library, "
                 f"{found.get('live_count', 0)} from Semantic Scholar and arXiv):"]
        for n, p in enumerate(papers, 1):
            where = "Athena id " + p["id"] if p.get("source") == "local" else p.get("source") or ""
            cites = f", {p['citation_count']} citations" if p.get("citation_count") else ""
            lines.append(f"\n{n}. {p.get('title')} ({p.get('year') or 'n.d.'}) {common.authors(p.get('authors'))}"
                         f"\n   {where}{cites} {p.get('url') or ''}".rstrip())
            if p.get("abstract"):
                lines.append(f"   {common.clip(p['abstract'], 400)}")
        return "\n".join(lines)

    @common.tool(mcp, READ)
    async def search_library(ctx: Context, query: str, category: Literal["paper", "company_blog", "community_blog"]
                             | None = None, limit: int = 10) -> str:
        """Search what Athena has already collected (papers, lab blogs, community posts), by keywords and meaning,
        with Athena's summaries. Faster than find_papers and only Athena's own items."""
        found = await common.get(ctx, "/search", q=query, category=category, limit=max(1, min(limit, 20)))
        items = found.get("items") or []
        if not items:
            return f"Nothing in Athena's library matches {query!r}; find_papers also searches outside it."
        return f"{len(items)} items for {query!r}:\n" + "\n".join(item_line(i, n) for n, i in enumerate(items, 1))

    @common.tool(mcp, READ)
    async def feed(ctx: Context, sort: Literal["relevance", "recent", "for_you"] = "relevance",
                   category: Literal["paper", "company_blog", "community_blog"] | None = None,
                   period: Literal["24h", "7d", "30d"] | None = None, limit: int = 15) -> str:
        """Athena's research feed, as on its Feed page: by relevance score (citations, engagement, recency, source
        authority), newest first, or "for_you" (ordered by this account's reactions and saves), with Athena's
        summaries."""
        page = await common.get(ctx, "/feed", sort=SORTS[sort], category=category, date_range=period,
                                limit=max(1, min(limit, 50)))
        items = page.get("items") or []
        if not items:
            return "The feed is empty for that choice."
        return "\n".join(item_line(i, n) for n, i in enumerate(items, 1))

    @common.tool(mcp, READ)
    async def rising(ctx: Context, window: Literal["7d", "30d"] = "7d", limit: int = 10) -> str:
        """Papers gaining citations fastest (Athena's Rising page), over the last 7 or 30 days."""
        page = await common.get(ctx, "/momentum/rising", window=window, limit=max(1, min(limit, 50)))
        items = page.get("items") or []
        if not items:
            return "No paper gained citations in that window yet (citation counts are taken daily)."
        return f"Rising over {window}:\n" + "\n".join(item_line(i, n) for n, i in enumerate(items, 1))

    @common.tool(mcp, READ)
    async def get_paper(ctx: Context, item_id: str) -> str:
        """One item of Athena's library in full: its metadata, Athena's summary and key takeaways (written on the
        spot if it has none yet), and this account's note on it."""
        i = await common.get(ctx, f"/items/{item_id}")
        lines = [f"# {i.get('title')}", "",
                 f"{common.authors(i.get('authors'), 8)}; {(i.get('source') or {}).get('name', '')}, "
                 f"{(i.get('published_at') or '')[:10]}; {i.get('citation_count') or 0} citations; "
                 f"score {i.get('score')}", f"{i.get('url') or ''}", f"In Athena: {common.link(f'/items/{item_id}')}"]
        if i.get("summary"):
            lines += ["", "Summary:", i["summary"]]
        takeaways = i.get("takeaways") or []
        if takeaways:
            lines += ["", "Key takeaways:"] + [f"- {t}" for t in takeaways]
        if i.get("content") or i.get("abstract"):
            lines += ["", "Abstract:", common.clip(i.get("abstract") or i.get("content"), 3000)]
        me = i.get("me") or {}
        if me.get("note"):
            lines += ["", f"Your note: {me['note']}"]
        return "\n".join(lines)
