"""
The REST API, called in-process with an agent's token.

Every MCP tool is a call to the routes the web app uses, so an agent can do what its account can in the browser and
no more: the same checks, daily allowances, GPU priorities and saved results (a review an agent asks for is on the
Reviews page). The calls skip the network: they go straight into the FastAPI app as ASGI requests whose scope
carries ``auth.AGENT``, the only kind of request on which an access token counts.

    await request(token, "GET", "/api/v1/reviews")              -> the JSON body (or text, for an export)
    async for event in stream(token, "POST", path, body): ...   -> a route's server-sent events, as they come
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from loguru import logger

from athena.api import auth

_app = None  # the FastAPI app, set by attach() when the app is made


def attach(app) -> None:
    global _app
    _app = app


class ApiError(Exception):
    """A route said no: its status and the detail it gave."""
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def detail_of(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # a validation error: name the fields
        detail = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', [])[1:]) or 'request'}: {e.get('msg')}"
                           for e in detail if isinstance(e, dict))
    return str(detail or body.decode(errors="replace")[:300].strip() or f"HTTP {status}")


class _Call:
    """One request into the app. The body arrives in pieces on ``chunks`` (None ends it); setting ``finished`` tells
    the route its client went away, which stops a stream."""

    def __init__(self, token: str, method: str, path: str, params: dict | None, body: Any):
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        self.scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
            "path": path, "raw_path": path.encode(), "root_path": "", "query_string": query.encode(),
            "headers": [(b"host", b"localhost"), (b"accept", b"application/json, text/event-stream"),
                        (b"content-type", b"application/json"), (b"authorization", f"Bearer {token}".encode())],
            "client": ("127.0.0.1", 0), "server": ("localhost", 80), auth.AGENT: True,
        }
        self.payload: bytes | None = json.dumps(body).encode() if body is not None else b""
        self.status: int | None = None
        self.content_type = ""
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.finished = asyncio.Event()

    async def receive(self) -> dict:
        if self.payload is not None:
            body, self.payload = self.payload, None
            return {"type": "http.request", "body": body, "more_body": False}
        await self.finished.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            headers = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
            self.content_type = headers.get("content-type", "")
        elif message["type"] == "http.response.body":
            if message.get("body"):
                await self.chunks.put(message["body"])
            if not message.get("more_body"):
                await self.chunks.put(None)

    async def run(self) -> None:
        if _app is None:
            raise RuntimeError("athena.mcp.api.attach(app) was not called")
        try:
            await _app(self.scope, self.receive, self.send)
        except Exception as exc:  # the route crashed after (or before) answering 500
            logger.warning(f"MCP: {self.scope['method']} {self.scope['path']} failed: {exc}")
            if self.status is None:
                self.status = 500
        finally:
            await self.chunks.put(None)

    def error(self, body: bytes) -> ApiError:
        return ApiError(self.status or 500, detail_of(self.status or 500, body))


async def request(token: str, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    """A route's answer: parsed JSON, text for anything else, None for an empty body. ApiError for 4xx and 5xx."""
    call = _Call(token, method, path, params, body)
    await call.run()
    parts = []
    while (chunk := call.chunks.get_nowait() if not call.chunks.empty() else None) is not None:
        parts.append(chunk)
    raw = b"".join(parts)
    if (call.status or 500) >= 400:
        raise call.error(raw)
    if not raw:
        return None
    if "json" in call.content_type:
        return json.loads(raw)
    return raw.decode(errors="replace")


async def stream(token: str, method: str, path: str, *, body: Any = None) -> AsyncIterator[dict]:
    """A server-sent-events route's events as they come. Leaving the loop early stops the route, like closing the
    page would."""
    call = _Call(token, method, path, None, body)
    task = asyncio.create_task(call.run())
    buffer, failed = b"", None
    try:
        while (chunk := await call.chunks.get()) is not None:
            if (call.status or 200) >= 400:
                failed = (failed or b"") + chunk
                continue
            buffer += chunk
            while b"\n\n" in buffer:
                event, buffer = buffer.split(b"\n\n", 1)
                for line in event.decode(errors="replace").splitlines():
                    data = line[5:].strip() if line.startswith("data:") else None
                    if data and data != "[DONE]":
                        try:
                            yield json.loads(data)
                        except ValueError:
                            continue
        if (call.status or 500) >= 400:
            raise call.error(failed or b"")
    finally:
        call.finished.set()
        with suppress(Exception):  # a route that does not stop within 10 s is cancelled
            await asyncio.wait_for(task, timeout=10)
