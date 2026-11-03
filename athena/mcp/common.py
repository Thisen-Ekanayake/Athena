"""
What every tool needs: the caller's token, the API with its refusals turned into errors the agent can read, links
into the web app, waiting on long work with progress, and text short enough for an agent's context.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from athena.api import auth
from athena.api.config import settings
from athena.mcp import api

POLL_SECONDS = 3.0
HEARTBEAT = 30.0  # progress at least this often, so proxies and clients see a long wait is alive

HINTS = {
    401: "The access token was not accepted (revoked, expired, or the account is off). Make a new one in "
         "Athena's Settings → Agents.",
    403: "This account may not do that in Athena.",
    429: "",  # the detail already says which allowance ran out and when it resets
}


def tool(mcp: MCPServer, annotations: ToolAnnotations):
    """Register a tool that answers in text (no output schema repeating it) and whose docstring, without its
    indentation, is its description."""
    def register(fn):
        return mcp.tool(annotations=annotations, structured_output=False,
                        description=inspect.cleandoc(fn.__doc__ or ""))(fn)
    return register


def token(ctx: Context) -> str:
    """The token the client sent. The door (athena.mcp.access) has checked it; every API call checks it again."""
    headers = ctx.headers or {}
    value = auth.bearer(headers.get("authorization") or headers.get("Authorization"))
    if not value:
        raise ToolError("No access token came with this request. Connect with the header "
                        "'Authorization: Bearer ath_…' (Athena's Settings → Agents).")
    return value


def refused(exc: api.ApiError) -> ToolError:
    hint = HINTS.get(exc.status, "")
    return ToolError(f"Athena refused ({exc.status}): {exc.detail}" + (f" {hint}" if hint else ""))


async def call(ctx: Context, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    try:
        return await api.request(token(ctx), method, "/api/v1" + path, params=params, body=body)
    except api.ApiError as exc:
        raise refused(exc) from None


async def get(ctx: Context, path: str, **params) -> Any:
    return await call(ctx, "GET", path, params=params)


async def post(ctx: Context, path: str, body: Any = None) -> Any:
    return await call(ctx, "POST", path, body=body if body is not None else {})


def link(path: str) -> str:
    """A page of the web app."""
    return f"{settings.PUBLIC_URL}{path}"


async def progress(ctx: Context, step: float, total: float | None, message: str) -> None:
    try:
        await ctx.report_progress(step, total, message)
    except Exception:  # a client that went away does not stop the work
        pass


class Reporter:
    """Progress while a stream runs: a new label at once, and the current one again whenever HEARTBEAT has passed
    (call ``beat`` on every event), so a model thinking for minutes still shows it is alive."""

    def __init__(self, ctx: Context):
        self.ctx, self.step, self.label, self.sent = ctx, 0, "", 0.0

    async def __call__(self, label: str) -> None:
        self.step += 1
        self.label = label
        self.sent = time.monotonic()
        await progress(self.ctx, self.step, None, label)

    async def beat(self) -> None:
        if self.label and time.monotonic() - self.sent >= HEARTBEAT:
            self.sent = time.monotonic()
            await progress(self.ctx, self.step, None, self.label)


class StillRunning(Exception):
    """The wait ran out; ``job`` is what to pass to wait_for."""
    def __init__(self, job: str, state: str):
        super().__init__(state)
        self.job = job
        self.state = state


async def wait(ctx: Context, job: str, check: Callable[[], Awaitable[tuple[bool, float, float | None, str]]],
               seconds: float | None = None) -> None:
    """Poll ``check`` (done, step, total, label) every few seconds, passing its label on as progress, until it is
    done or ``seconds`` (MCP_WAIT_SECONDS) run out, then raise StillRunning with the job to wait on."""
    deadline = time.monotonic() + (settings.MCP_WAIT_SECONDS if seconds is None else seconds)
    last, sent = None, 0.0
    while True:
        done, step, total, label = await check()
        if done:
            return
        if label != last or time.monotonic() - sent >= HEARTBEAT:
            await progress(ctx, step, total, label)
            last, sent = label, time.monotonic()
        if time.monotonic() >= deadline:
            raise StillRunning(job, label)
        await asyncio.sleep(POLL_SECONDS)


def still_running(exc: StillRunning, what: str) -> str:
    return (f"{what} is still running in Athena ({exc.state}). It goes on without you: call wait_for with "
            f"job \"{exc.job}\" to wait for it again and get the result.")


# ── text ─────────────────────────────────────────────────────────────


def clip(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def authors(names: Any, n: int = 3) -> str:
    names = [a.get("name") if isinstance(a, dict) else a for a in (names or [])]
    names = [a for a in names if a]
    return ", ".join(names[:n]) + (" et al." if len(names) > n else "")


def compact(value: Any, *, width: int = 300, items: int = 25, depth: int = 0) -> str:
    """JSON as indented lines, without empty values, long strings clipped and long lists cut: a generic answer an
    agent can read without spending its context on punctuation."""
    pad = "  " * depth
    if isinstance(value, dict):
        lines = []
        for key, v in value.items():
            if v in (None, "", [], {}):
                continue
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(compact(v, width=width, items=items, depth=depth + 1))
            else:
                lines.append(f"{pad}{key}: {clip(v, width)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for v in value[:items]:
            if isinstance(v, (dict, list)):
                inner = compact(v, width=width, items=items, depth=depth + 1).lstrip()
                lines.append(f"{pad}- {inner}")
            else:
                lines.append(f"{pad}- {clip(v, width)}")
        if len(value) > items:
            lines.append(f"{pad}… and {len(value) - items} more")
        return "\n".join(lines)
    return pad + clip(value, width)
