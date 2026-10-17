"""
Share links to maps (the read-only pages are athena.api.routers.share).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import User
from athena.core.config_store import set_setting
from athena.database import shares
from athena.api.routers.evolution._common import _built_topic_or_409, _topic_or_404

router = APIRouter()


class ShareRequest(BaseModel):
    expires_days: Literal[7, 30, 90] | None = None


class SharingRequest(BaseModel):
    enabled: bool


@router.get("/sharing")
def sharing_status():
    """Whether maps can be shared at all, so the page knows to offer it."""
    return {"enabled": shares.sharing_enabled()}


@router.put("/sharing", dependencies=[Depends(auth.require_admin)])
def set_sharing(body: SharingRequest):
    """Switch every share link on or off at once; links switched off come back when sharing does."""
    set_setting(shares.SHARING_KEY, "true" if body.enabled else "false")
    return {"enabled": body.enabled}


@router.get("/shares")
def all_shares(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    """The active links to every map: the user's own, or everyone's for an admin."""
    return {"enabled": shares.sharing_enabled(), "shares": shares.list_for(session, user)}


@router.get("/topics/{slug}/shares")
def topic_shares(slug: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    topic = _topic_or_404(session, slug)
    return {"enabled": shares.sharing_enabled(), "shares": shares.list_for(session, user, topic)}


@router.post("/topics/{slug}/shares", status_code=201)
def share_topic(slug: str, body: ShareRequest, session: Session = Depends(get_db),
                user: User = Depends(auth.active_user)):
    """A read-only link to the map for people without an account; the page builds the URL from the token."""
    if not shares.sharing_enabled():
        raise HTTPException(status_code=403, detail="An admin has switched sharing off")
    topic = _built_topic_or_409(session, slug)
    share = shares.create(session, topic, user, body.expires_days)
    return shares.as_dict(share, user.display_name)


@router.delete("/shares/{share_id}", status_code=204)
def revoke_share(share_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    revoked = shares.revoke(session, share_id, user)
    if revoked is None:
        raise HTTPException(status_code=404, detail="No such link")
    if revoked is False:
        raise HTTPException(status_code=403, detail="Only the person who made a link, or an admin, can revoke it")
