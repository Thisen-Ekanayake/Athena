"""
Access tokens for agents.

GET    /api/v1/tokens        — your tokens (never the tokens themselves)
POST   /api/v1/tokens        — make one; the response holds the token, shown this once
DELETE /api/v1/tokens/{id}   — revoke one

A token lets an agent (Claude Code, another MCP client) use the MCP server at /mcp in your account's name, with
your daily allowances. Only a person signed in with the browser can manage tokens; an agent cannot make more.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import ApiToken, User

router = APIRouter(prefix="/api/v1/tokens", tags=["Access tokens"])

MAX_TOKENS = 20


def browser_user(request: Request, user: User = Depends(auth.active_user)) -> User:
    if auth.from_agent(request):
        raise HTTPException(status_code=403, detail="Access tokens are managed in Settings, not by an agent")
    return user


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    expires_days: int | None = Field(None, ge=1, le=3650)


def token_out(t: ApiToken) -> dict:
    return {"id": str(t.id), "name": t.name, "hint": t.hint,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None}


def _mine(db: Session, user: User) -> list[ApiToken]:
    return list(db.execute(select(ApiToken).where(ApiToken.user_id == user.id)
                           .order_by(ApiToken.created_at.desc())).scalars())


@router.get("")
def list_tokens(db: Session = Depends(get_db), user: User = Depends(browser_user)):
    return [token_out(t) for t in _mine(db, user)]


@router.post("", status_code=201)
def create_token(body: TokenCreate, db: Session = Depends(get_db), user: User = Depends(browser_user)):
    if len(_mine(db, user)) >= MAX_TOKENS:
        raise HTTPException(status_code=409, detail=f"You have {MAX_TOKENS} tokens; revoke one first")
    row, token = auth.create_api_token(db, user, " ".join(body.name.split()), body.expires_days)
    return token_out(row) | {"token": token}


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: UUID, db: Session = Depends(get_db), user: User = Depends(browser_user)):
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Token not found")
    db.delete(row)
    db.commit()
