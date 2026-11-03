"""
Athena's MCP server: agents (Claude Code, other MCP clients) use Athena as its web app is used.

Served over Streamable HTTP at /mcp in the API (athena.api.main), behind an access token (Settings → Agents).
Every tool calls the routes the web app calls, in-process and in the token's account (athena.mcp.api), so the
agent gets the same answers, limits and saved results as the person would in the browser.

    claude mcp add --transport http athena http://localhost:8000/mcp --header "Authorization: Bearer ath_…"

Tools, by module: research (Athena's model does the work: reviews, map answers, idea checks, new maps, chats),
papers (search and the feed), maps (reading a map), mine (the account's reviews, artifacts, projects, lists,
notes), admin (status, syncs, pausing background work, usage). Resources give maps, reviews, artifacts and papers
by URI; prompts start the common requests.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse

from athena.api.config import settings
from athena.mcp import admin, common, maps, mine, papers, research
from athena.mcp.access import RequireToken

INSTRUCTIONS = """\
Athena is a research platform with its own model, library and research maps (a field's papers, lineage, \
milestones and open problems). It does research work itself.

When the user asks for research (a literature review, an answer from a field's papers, whether an idea is new, a \
map of a field, a chat with Athena), call the Athena tool that does it and pass on what Athena returns. Do not \
search, read papers or write the result yourself as well, and do not rewrite Athena's result unless the user asks: \
the point is that Athena does the work. Long tasks report progress; if a tool hands back a job, wait_for it.

Everything is saved in the user's Athena account (reviews on its Reviews page, maps for everyone, chats and \
artifacts in Chats and Projects) and the results link to it. Daily allowances apply as in the web app; a refusal \
says which ran out. Maps are named by their name or slug; list_maps lists them."""

mcp = MCPServer(
    "Athena", title="Athena research", instructions=INSTRUCTIONS, website_url=settings.PUBLIC_URL,
    version="1.0.0",
)

for module in (research, papers, maps, mine, admin):
    module.register(mcp)


# ── resources ────────────────────────────────────────────────────────


@mcp.resource("athena://maps/{slug}", mime_type="text/plain", description="A research map as text (compact digest)")
async def map_resource(slug: str, ctx: Context) -> str:
    d = await common.get(ctx, f"/evolution/topics/{slug}/digest", level="compact")
    return d["text"]


@mcp.resource("athena://reviews/{review_id}", mime_type="text/markdown", description="A literature review")
async def review_resource(review_id: str, ctx: Context) -> str:
    return research.review_text(await common.get(ctx, f"/reviews/{review_id}"))


@mcp.resource("athena://artifacts/{artifact_id}", mime_type="text/markdown", description="An artifact's text")
async def artifact_resource(artifact_id: str, ctx: Context) -> str:
    a = await common.get(ctx, f"/artifacts/{artifact_id}")
    return f"# {a.get('title')}\n\n{a.get('content') or ''}"


@mcp.resource("athena://papers/{item_id}", mime_type="text/plain", description="A paper of Athena's library")
async def paper_resource(item_id: str, ctx: Context) -> str:
    return common.compact(await common.get(ctx, f"/items/{item_id}"), width=2000)


# ── prompts ──────────────────────────────────────────────────────────


@mcp.prompt(title="Literature review by Athena")
def lit_review(topic: str) -> str:
    """Have Athena find the research on a topic and write a literature review."""
    return (f"Use Athena's literature_review tool for the topic \"{topic}\". Show me Athena's review as it is, "
            "with its references and the link to it in Athena. Then list three papers from it worth reading first.")


@mcp.prompt(title="Catch up on a field")
def catch_up(map: str) -> str:
    """What changed in a research map lately and what to read."""
    return (f"From Athena's research map \"{map}\": show what its latest refreshes changed (map_details view "
            "changes), its open problems (view gaps) and its papers rising fastest (view rising). Keep Athena's "
            "wording; add a three-line summary at the end.")


@mcp.prompt(title="Is my idea new?")
def idea_new(idea: str) -> str:
    """Check a research idea against Athena's maps."""
    return ("Use Athena's check_idea tool on this idea and show its verdict, closest papers and open problems:"
            f"\n\n{idea}")


# ── HTTP ─────────────────────────────────────────────────────────────


def _security() -> TransportSecuritySettings | None:
    """Localhost only (the SDK's guard against DNS rebinding), plus MCP_ALLOWED_HOSTS; "*" switches the guard off
    for a proxy that checks Host itself."""
    hosts = settings.MCP_ALLOWED_HOSTS
    if not hosts:
        return None
    if "*" in hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    return TransportSecuritySettings(
        allowed_hosts=local + hosts + [f"{h}:*" for h in hosts if ":" not in h],
        allowed_origins=[f"{scheme}://{h}" for h in local + hosts for scheme in ("http", "https")])


class Endpoint:
    """/mcp: the token check in front of the MCP app of the running API. A new app (and session manager) per start
    of the API, since a session manager runs once."""

    def __init__(self):
        self.app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            await PlainTextResponse("The MCP server is not running", status_code=503)(scope, receive, send)
            return
        await self.app(scope, receive, send)


endpoint = Endpoint()


@asynccontextmanager
async def running():
    """Serve /mcp while the API runs (from its lifespan: a mounted app's own lifespan never runs)."""
    endpoint.app = RequireToken(mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=_security()))
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        endpoint.app = None
