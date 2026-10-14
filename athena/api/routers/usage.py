"""
Usage and cost (ROADMAP R1): what each person has used, and for admins what the whole app has, with the
monthly budget, the monthly token cap and the daily allowances they set.
"""
from __future__ import annotations

import redis as redis_lib
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.api.routers.app_settings import save_settings
from athena.core import usage
from athena.core.config_store import get_setting
from athena.core.models import User

router = APIRouter(prefix="/api/v1/usage", tags=["Usage"])

# Settings this page changes; an empty value falls back to the environment, then the default.
BUDGET_SETTINGS = {"MONTHLY_BUDGET_USD": "0", "USER_MONTHLY_TOKENS": "0"}
LIMIT_SETTINGS = {f"LIMIT_{action.upper()}_PER_DAY": str(n) for action, n in auth.LIMITS.items()} | {
    f"LIMIT_{action.upper()}_TOKENS_PER_DAY": str(n) for action, n in auth.TOKEN_LIMITS.items()}
SETTINGS = BUDGET_SETTINGS | LIMIT_SETTINGS


class UsageSettingsUpdate(BaseModel):
    values: dict[str, str]


def _settings() -> dict:
    labels = {f"LIMIT_{a.upper()}_PER_DAY": label for a, label in auth.LIMIT_LABELS.items()} | {
        f"LIMIT_{a.upper()}_TOKENS_PER_DAY": f"tokens for {auth.LIMIT_LABELS[a]}" for a in auth.TOKEN_LIMITS}
    return {"values": {key: get_setting(key) for key in SETTINGS}, "defaults": SETTINGS, "limit_labels": labels}


@router.get("/me")
def my_usage(user: User = Depends(auth.active_user), session: Session = Depends(get_db),
             r: redis_lib.Redis = Depends(get_redis)):
    """This month's model use, and what is left of today's allowances (admins have none)."""
    return usage.user_report(session, user.id) | {
        "role": user.role, "allowances": auth.allowances(r, user),
        "budget_reached": usage.app_over_budget(session) and user.role != "admin"}


@router.get("/summary")
def app_usage(days: int | None = Query(None, ge=1, le=366), session: Session = Depends(get_db),
              _admin: User = Depends(auth.require_admin)):
    """The whole app's model use this month (or the last ``days`` days), by feature, model, person and day."""
    return usage.app_report(session, days)


@router.get("/settings")
def usage_settings(_admin: User = Depends(auth.require_admin)):
    return _settings()


@router.put("/settings")
def update_usage_settings(body: UsageSettingsUpdate, session: Session = Depends(get_db),
                          _admin: User = Depends(auth.require_admin)):
    save_settings(session, body.values, SETTINGS, numeric={"MONTHLY_BUDGET_USD"},
                  whole=set(SETTINGS) - {"MONTHLY_BUDGET_USD"})
    return _settings()
