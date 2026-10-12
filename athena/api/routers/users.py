"""
Athena Layer 5 — Users Router (admin only)

GET   /api/v1/users                        — every account
POST  /api/v1/users                        — create one; answers with a temporary password, shown once
PATCH /api/v1/users/{user_id}              — change the name, role or whether the account is active
POST  /api/v1/users/{user_id}/reset-password — a new temporary password (there is no email to send a link to)

Deactivating an account or resetting its password ends its sessions. The last
active admin cannot be demoted or deactivated.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.api.routers.auth import user_out
from athena.core.models import User

router = APIRouter(prefix="/api/v1/users", tags=["Users"], dependencies=[Depends(auth.require_admin)])


class UserCreateRequest(BaseModel):
    email: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["admin", "user"] = "user"


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


def _user_or_404(db: Session, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    return user


def _other_active_admins(db: Session, user: User) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True),
                                                       User.id != user.id))


@router.get("")
def list_users(db: Session = Depends(get_db)):
    return [user_out(u) for u in db.execute(select(User).order_by(User.created_at)).scalars()]


@router.post("", status_code=201)
def create_user(body: UserCreateRequest, db: Session = Depends(get_db)):
    email = auth.normalise_email(body.email)
    if db.execute(select(User.id).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    password = auth.temporary_password()
    user = User(email=email, display_name=body.display_name.strip(), role=body.role,
                password_hash=auth.hash_password(password), must_change_password=True)
    db.add(user)
    db.commit()
    return user_out(user) | {"temporary_password": password}


@router.patch("/{user_id}")
def update_user(user_id: UUID, body: UserUpdateRequest, db: Session = Depends(get_db)):
    user = _user_or_404(db, user_id)
    losing_admin = (body.role == "user" and user.role == "admin") or (body.is_active is False and user.role == "admin")
    if losing_admin and _other_active_admins(db, user) == 0:
        raise HTTPException(status_code=409, detail="Athena needs at least one active admin")
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    if body.is_active is False:
        auth.revoke_sessions(db, user.id)
    return user_out(user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: UUID, db: Session = Depends(get_db)):
    user = _user_or_404(db, user_id)
    password = auth.temporary_password()
    user.password_hash = auth.hash_password(password)
    user.must_change_password = True
    db.commit()
    auth.revoke_sessions(db, user.id)
    return user_out(user) | {"temporary_password": password}
