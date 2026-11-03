"""
The account's own things: its reviews, artifacts (Markdown documents), projects, saved lists and notes. Agents read
them and add to them; deleting stays in the web app.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.mcp import common, lookup
from athena.mcp.research import review_text

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def register(mcp: MCPServer) -> None:
    @common.tool(mcp, READ)
    async def my_reviews(ctx: Context, review_id: str | None = None, format: Literal["markdown", "bibtex"] =
                         "markdown") -> str:
        """The literature reviews this account has had Athena write: a list, or one review in full (`review_id`),
        as Markdown or as BibTeX of its references."""
        if not review_id:
            reviews = (await common.get(ctx, "/reviews"))["reviews"]
            if not reviews:
                return "No reviews yet; literature_review has Athena write one."
            return "\n".join(f"- {r['title']} (id {r['id']}; {r['status']}; {r.get('cited', 0)} sources; "
                             f"{(r.get('created_at') or '')[:10]})" for r in reviews)
        if format == "bibtex":
            return await common.get(ctx, f"/reviews/{review_id}/export", format="bib")
        r = await common.get(ctx, f"/reviews/{review_id}")
        if r["status"] != "done":
            return f"The review is {r['status']}; wait_for job \"review:{review_id}\" waits for it."
        return review_text(r)

    @common.tool(mcp, READ)
    async def list_artifacts(ctx: Context, project: str | None = None) -> str:
        """This account's artifacts (Markdown documents it or Athena's chat wrote), all or one project's."""
        project_id = (await lookup.find_project(ctx, project))["id"] if project else None
        rows = (await common.get(ctx, "/artifacts", project_id=project_id))["artifacts"]
        if not rows:
            return "No artifacts yet."
        return "\n".join(f"- {a['title']} (id {a['id']}; version {a.get('version')}; "
                         f"{(a.get('updated_at') or '')[:10]})" for a in rows)

    @common.tool(mcp, READ)
    async def read_artifact(ctx: Context, artifact_id: str, version: int | None = None) -> str:
        """An artifact's text (its latest version, or an older one)."""
        path = f"/artifacts/{artifact_id}" + (f"/versions/{version}" if version else "")
        a = await common.get(ctx, path)
        return (f"# {a.get('title')} (version {a.get('version')}; {common.link('/chats')})\n\n"
                + (a.get("content") or ""))

    @common.tool(mcp, WRITE)
    async def write_artifact(ctx: Context, title: str, content: str, project: str | None = None) -> str:
        """Save a Markdown document to this account's artifacts in Athena (optionally in a project), where the user
        can open, edit and export it. Use it to keep what Athena produced, such as a review or an answer."""
        project_id = (await lookup.find_project(ctx, project))["id"] if project else None
        a = await common.post(ctx, "/artifacts", {"title": title, "content": content, "project_id": project_id})
        return f"Saved the artifact {a['title']!r} (id {a['id']}, version {a.get('version', 1)})."

    @common.tool(mcp, WRITE)
    async def edit_artifact(ctx: Context, artifact_id: str, title: str | None = None, content: str | None = None,
                            find: str | None = None, replace: str | None = None) -> str:
        """Change an artifact: a new `title`, the whole new `content`, or one exact passage (`find`) replaced with
        `replace`. Every change is a new version; older ones stay."""
        body: dict = {}
        if title:
            body["title"] = title
        if content is not None:
            body["content"] = content
        elif find:
            current = (await common.get(ctx, f"/artifacts/{artifact_id}")).get("content") or ""
            if find not in current:
                raise ToolError("That passage is not in the artifact; read_artifact shows its text")
            body["content"] = current.replace(find, replace or "", 1)
        if not body:
            raise ToolError("Give a title, content, or a passage to find and replace")
        a = await common.call(ctx, "PATCH", f"/artifacts/{artifact_id}", body=body)
        return f"The artifact {a['title']!r} is now version {a.get('version')}."

    @common.tool(mcp, READ)
    async def projects(ctx: Context, project: str | None = None) -> str:
        """This account's projects, or one in full: its instructions, papers, maps, reviews, files, chats and
        artifacts."""
        if not project:
            rows = (await common.get(ctx, "/projects"))["projects"]
            if not rows:
                return "No projects yet."
            lines = []
            for p in rows:
                counts = ", ".join(f"{n} {k}" for k, n in (p.get("counts") or {}).items() if n)
                lines.append(f"- {p['name']} (id {p['id']}{'; ' + counts if counts else ''})"
                             + (f": {common.clip(p['description'], 160)}" if p.get("description") else ""))
            return "\n".join(lines)
        p = await lookup.find_project(ctx, project)
        full = await common.get(ctx, f"/projects/{p['id']}")
        return common.compact(full, width=200, items=40) + f"\n\nOpen in Athena: {common.link('/projects/' + p['id'])}"

    @common.tool(mcp, WRITE)
    async def add_to_project(ctx: Context, project: str, kind: Literal["paper", "map", "review", "idea_check", "list"],
                             id: str) -> str:
        """Add something to a project, as its Add button does: a paper (its Athena id), a map (name or slug), a
        review or idea check (id), or a saved list (name or id). Its text joins the project's chat search."""
        p = await lookup.find_project(ctx, project)
        if kind == "map":
            id = (await lookup.find_map(ctx, id, built=False))["slug"]
        elif kind == "list":
            id = str((await lookup.find_list(ctx, id))["id"])
        added = await common.post(ctx, f"/projects/{p['id']}/items", {"kind": kind, "id": id})
        return f"Added to {p['name']}: {added.get('title') or id} ({kind})."

    @common.tool(mcp, READ)
    async def saved_lists(ctx: Context, list: str | None = None) -> str:
        """This account's saved lists, or the items in one (by name or id)."""
        if not list:
            rows = await common.get(ctx, "/lists")
            return "\n".join(f"- {x['name']} (id {x['id']}; {x.get('item_count', 0)} items)" for x in rows) \
                or "No saved lists yet."
        found = await lookup.find_list(ctx, list)
        page = await common.get(ctx, f"/lists/{found['id']}/items")
        items = page.get("items", page) if isinstance(page, dict) else page
        from athena.mcp.papers import item_line
        return f"{found['name']}:\n" + ("\n".join(item_line(i) for i in items) or "(empty)")

    @common.tool(mcp, WRITE)
    async def save_to_list(ctx: Context, item_id: str, list: str) -> str:
        """Save an item of Athena's library (its id) to a saved list, made if no list has that name."""
        try:
            found = await lookup.find_list(ctx, list)
        except ToolError:
            found = await common.post(ctx, "/lists", {"name": list})
        await common.post(ctx, f"/lists/{found['id']}/items", {"item_id": item_id})
        return f"Saved to {found['name']}."

    @common.tool(mcp, WRITE)
    async def write_note(ctx: Context, item_id: str, note: str) -> str:
        """Set this account's private note on an item of Athena's library (an empty note removes it)."""
        if not note.strip():
            await common.call(ctx, "DELETE", f"/items/{item_id}/note")
            return "Removed the note."
        await common.call(ctx, "PUT", f"/items/{item_id}/note", body={"body": note})
        return "Saved the note."
