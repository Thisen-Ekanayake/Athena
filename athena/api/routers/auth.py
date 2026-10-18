"""
Logging in and out, and creating the first account.

GET  /api/v1/auth/status    — whether the first admin still has to be created, and who is logged in
POST /api/v1/auth/setup     — create the first (admin) account; refused once any account exists
POST /api/v1/auth/login     — start a session (httpOnly cookie)
POST /api/v1/auth/logout    — end it
GET  /api/v1/auth/me        — the logged-in account
POST /api/v1/auth/password  — change your own password (required after a temporary one)
POST /api/v1/auth/onboarding — mark the setup guide done (or skipped), or bring it back

There is no public sign-up: the admin creates accounts (routers/users.py).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.core.models import SavedList, User

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

LOGIN_ATTEMPTS = 10           # failed logins allowed per email and address ...
LOGIN_WINDOW_SECONDS = 15 * 60  # ... in this window


class SetupRequest(BaseModel):
    email: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class PasswordRequest(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class OnboardingRequest(BaseModel):
    done: bool


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def user_out(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role,
            "is_active": user.is_active, "must_change_password": user.must_change_password,
            "created_at": _iso(user.created_at), "last_login_at": _iso(user.last_login_at),
            # None until the setup guide is finished or skipped; the app opens the guide until then
            "onboarded_at": _iso(getattr(user, "onboarded_at", None))}


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    needs_setup = db.scalar(select(func.count(User.id))) == 0
    user = None if needs_setup else auth.session_user(db, request.cookies.get(auth.COOKIE))
    return {"needs_setup": needs_setup, "user": user_out(user) if user else None}


@router.post("/setup", status_code=201)
def setup(body: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """The first account, which is the admin. It takes over any saved lists made before accounts existed."""
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(status_code=409, detail="Athena already has an admin; log in instead")
    auth.check_password(body.password)
    user = User(email=auth.normalise_email(body.email), display_name=body.display_name.strip(),
                password_hash=auth.hash_password(body.password), role="admin")
    db.add(user)
    db.flush()
    db.execute(update(SavedList).where(SavedList.user_id.is_(None)).values(user_id=user.id))
    db.commit()
    logger.info(f"Created the admin account {user.email}")
    auth.set_cookie(response, request, auth.create_session(db, user, request.headers.get("user-agent")))
    return user_out(user)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db),
          r=Depends(get_redis)):
    email = body.email.strip().lower()
    key = f"login_fail:{email}:{request.client.host if request.client else '-'}"
    if int(r.get(key) or 0) >= LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many failed attempts; try again in 15 minutes")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not auth.verify_password(user.password_hash, body.password) or not user.is_active:
        if r.incr(key) == 1:
            r.expire(key, LOGIN_WINDOW_SECONDS)
        # One message for every failure, so the form does not reveal which emails have accounts.
        raise HTTPException(status_code=401, detail="Wrong email or password")
    r.delete(key)
    auth.set_cookie(response, request, auth.create_session(db, user, request.headers.get("user-agent")))
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.revoke_token(db, token)
    auth.clear_cookie(response)


@router.get("/me")
def me(user: User = Depends(auth.current_user)):
    return user_out(user)


@router.post("/password")
def change_password(body: PasswordRequest, request: Request, user: User = Depends(auth.current_user),
                    db: Session = Depends(get_db)):
    """Change your own password; every other session of the account ends."""
    if not auth.verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=403, detail="The current password is not right")
    auth.check_password(body.new_password)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Choose a password different from the current one")
    user.password_hash = auth.hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    auth.revoke_sessions(db, user.id, keep_token=request.cookies.get(auth.COOKIE))
    return user_out(user)


@router.post("/onboarding")
def onboarding(body: OnboardingRequest, user: User = Depends(auth.active_user), db: Session = Depends(get_db)):
    """``done``: the guide is finished or skipped and stays away. Not done: it opens again on the next page."""
    user.onboarded_at = datetime.now(timezone.utc) if body.done else None
    db.commit()
    return user_out(user)
