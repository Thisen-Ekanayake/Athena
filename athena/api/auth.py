"""
Athena Layer 5 — Accounts, sessions and per-user limits

A login creates an opaque session token, stored only as its SHA-256 in
``user_sessions`` and sent back in an httpOnly cookie. Unlike a signed JWT, a
session can be ended at once: logging out, deactivating an account or resetting
its password revokes it. The cookie is SameSite=Lax, so browsers leave it off
cross-site POST, PATCH and DELETE requests, and CORS only admits the frontend's
origins; together they stand in for a CSRF token.

Dependencies:
    current_user   any logged-in account (the auth routes use it)
    active_user    a logged-in account that has no pending password change (every other route)
    require_admin  an active admin
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from athena.api.deps import get_db, get_redis
from athena.core.config_store import get_setting
from athena.core.models import User, UserSession

COOKIE = "athena_session"
SESSION_DAYS = 30
TOUCH_EVERY = timedelta(hours=1)  # the rolling expiry is pushed back at most hourly, not on every request
MIN_PASSWORD = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_CHANGE_REQUIRED = "password_change_required"

# Daily allowances for calls that take GPU time (or money with a hosted model). Admins have none.
LIMITS = {"qa": 100, "lit_review": 10, "map_proposal": 10, "map_build": 3}
LIMIT_LABELS = {"qa": "questions", "lit_review": "literature reviews", "map_proposal": "map searches",
                "map_build": "map builds"}

_hasher = PasswordHasher()  # argon2id


# ── passwords ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Use at least {MIN_PASSWORD} characters")


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That is not an email address")
    return email


def temporary_password() -> str:
    """A password the admin passes on once; the user has to replace it at the next login."""
    return secrets.token_urlsafe(9)


# ── sessions ───────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite hands timestamps back without a zone; they were stored in UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(UserSession(user_id=user.id, token_hash=_digest(token), expires_at=now + timedelta(days=SESSION_DAYS),
                       last_seen_at=now, user_agent=(user_agent or "")[:300] or None))
    user.last_login_at = now
    db.commit()
    return token


def revoke_sessions(db: Session, user_id, keep_token: str | None = None) -> None:
    """End every session of ``user_id``, except the one making the request when ``keep_token`` is given."""
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_token:
        stmt = stmt.where(UserSession.token_hash != _digest(keep_token))
    db.execute(stmt)
    db.commit()


def revoke_token(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))
    db.commit()


def set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def session_user(db: Session, token: str | None) -> User | None:
    """The active account behind ``token``, pushing the session's expiry back while it is used."""
    if not token:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == _digest(token))).scalar_one_or_none()
    if sess is None:
        return None
    now = _now()
    if _aware(sess.expires_at) <= now:
        db.delete(sess)
        db.commit()
        return None
    user = sess.user
    if user is None or not user.is_active:
        return None
    if sess.last_seen_at is None or now - _aware(sess.last_seen_at) > TOUCH_EVERY:
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(days=SESSION_DAYS)
        db.commit()
    return user


# ── dependencies ───────────────────────────────────────────────────────


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Log in to continue")
    return user


def active_user(user: User = Depends(current_user)) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED)
    return user


def require_admin(user: User = Depends(active_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin can do this")
    return user


# ── daily limits ───────────────────────────────────────────────────────


def daily_limit(action: str) -> int:
    try:
        return int(get_setting(f"LIMIT_{action.upper()}_PER_DAY") or LIMITS[action])
    except ValueError:
        return LIMITS[action]


def use(r, user: User, action: str) -> None:
    """Count one ``action`` for ``user`` today; past the daily limit, refuse with 429. Admins are not counted."""
    if user.role == "admin":
        return
    key = f"limit:{user.id}:{action}:{_now():%Y-%m-%d}"
    used = int(r.incr(key))
    if used == 1:
        r.expire(key, 2 * 86400)
    limit = daily_limit(action)
    if used > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"You have used today's {limit} {LIMIT_LABELS[action]}. "
                                   "The allowance resets at midnight UTC.")


def spend(action: str):
    """A dependency form of ``use`` for routes where every call counts."""
    def check(user: User = Depends(active_user), r=Depends(get_redis)) -> User:
        use(r, user, action)
        return user
    return check
