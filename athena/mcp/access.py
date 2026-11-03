"""
The door: a request to /mcp without a valid access token is turned away with 401 before MCP reads it.

Every API call a tool makes checks the token again (athena.api.auth.current_user), so a token revoked mid-session
stops working at its next call.
"""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from athena.api import auth


def valid(token: str | None) -> bool:
    if not token:
        return False
    from athena.database.db import SessionLocal
    with SessionLocal() as db:
        return auth.token_user(db, token) is not None


class RequireToken:
    """ASGI middleware in front of the MCP app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            if not await run_in_threadpool(valid, auth.bearer(headers.get("authorization"))):
                refuse = JSONResponse(
                    {"error": "invalid_token",
                     "error_description": "Athena needs an access token: make one in Settings → Agents and send it "
                                          "as 'Authorization: Bearer ath_…'"},
                    status_code=401, headers={"WWW-Authenticate": 'Bearer realm="athena", error="invalid_token"'})
                await refuse(scope, receive, send)
                return
        await self.app(scope, receive, send)
