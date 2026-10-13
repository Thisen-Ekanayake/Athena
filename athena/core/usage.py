"""
Usage and cost (ROADMAP R1): every model call is counted here, and the monthly budget is checked here.

A call someone made (a question, an idea check, a literature review) is written at once, so the budget sees it
before their next one. Background calls (summaries, map building, feed embeddings) can come by the thousand, so
each process sums them per feature and model and writes one row a minute.

Settings (env or the settings table):
- MONTHLY_BUDGET_USD: what the whole app may spend on models in a calendar month (UTC); 0 means no budget.
  Past it, users other than admins are refused and background summaries pause.
- USER_MONTHLY_TOKENS: the tokens each user other than an admin may use in a month; 0 means no cap. With a local
  model every call costs nothing, so this is the limit that keeps one person from holding the GPU.
- LLM_PRICE_IN_PER_M, LLM_PRICE_OUT_PER_M, EMBED_PRICE_PER_M: USD per million tokens (``llm.cost``).
"""
from __future__ import annotations

import atexit
import threading
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select

from athena.core.config_store import get_setting

FLUSH_SECONDS = 60.0
ALERT_THRESHOLDS = (80, 100)  # percent of the monthly budget at which admins get an inbox entry
ALERT_MARKER = "BUDGET_ALERT_{month}"

# What each feature is called on the usage page.
FEATURES = {
    "qa": "Questions about papers",
    "map_qa": "Questions to maps",
    "idea_check": "Idea checks",
    "lit_review": "Literature reviews",
    "reading_notes": "Reading-path notes",
    "summary": "Summaries",
    "cluster_label": "Cluster labels",
    "trending_brief": "Trending briefs",
    "map_proposal": "Map proposals",
    "map_build": "Map building",
    "map_embed": "Map embeddings",
    "feed_embed": "Feed embeddings",
    "scoring": "Scoring",
    "search": "Search",
}


def _session():
    from athena.database.db import SessionLocal
    return SessionLocal()


def _write(rows: list[dict]) -> None:
    from athena.core.models import UsageEvent
    try:
        with _session() as session:
            session.add_all(UsageEvent(**row) for row in rows)
            session.commit()
    except Exception as exc:  # usage is bookkeeping: it never breaks the call it records
        logger.warning(f"Usage not recorded ({len(rows)} rows): {exc}")


# ── recording ──────────────────────────────────────────────────────────


_lock = threading.Lock()
_pending: dict[tuple[str, str, str], dict] = {}
_timer: threading.Timer | None = None


def add(feature: str, model: str, input_tokens: int, output_tokens: int = 0, kind: str = "chat",
        user_id: UUID | None = None) -> None:
    """Count one model call. Never raises."""
    try:
        from athena.core import llm
        input_tokens, output_tokens = max(int(input_tokens or 0), 0), max(int(output_tokens or 0), 0)
        cost = llm.cost(input_tokens, output_tokens, kind)
        row = {"feature": feature, "kind": kind, "model": model or "", "calls": 1, "input_tokens": input_tokens,
               "output_tokens": output_tokens, "cost_usd": cost}
        if user_id is not None:
            _write([row | {"user_id": user_id, "created_at": datetime.now(timezone.utc)}])
            return
        global _timer
        with _lock:
            key = (feature, kind, row["model"])
            if key in _pending:
                for field in ("calls", "input_tokens", "output_tokens", "cost_usd"):
                    _pending[key][field] += row[field]
            else:
                _pending[key] = row
            if _timer is None:
                _timer = threading.Timer(FLUSH_SECONDS, flush)
                _timer.daemon = True
                _timer.start()
    except Exception as exc:
        logger.warning(f"Usage not counted: {exc}")


def flush() -> None:
    """Write the background calls summed so far in this process."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()  # a no-op when the timer itself is flushing
        rows, _timer = list(_pending.values()), None
        _pending.clear()
    if rows:
        now = datetime.now(timezone.utc)
        _write([row | {"created_at": now} for row in rows])


atexit.register(flush)


def tokens_of(usage) -> tuple[int, int]:
    """(input, output) tokens from an OpenAI-style ``usage``, an object or a dict; (0, 0) when there is none."""
    if usage is None:
        return 0, 0
    get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
    return int(get("prompt_tokens", 0) or 0), int(get("completion_tokens", 0) or 0)


# ── the month ──────────────────────────────────────────────────────────


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(now: datetime | None = None) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def _number(key: str) -> float:
    try:
        return max(float(get_setting(key) or 0), 0.0)
    except ValueError:
        return 0.0


def budget_usd() -> float:
    return _number("MONTHLY_BUDGET_USD")


def user_token_cap() -> int:
    return int(_number("USER_MONTHLY_TOKENS"))


def month_spend(session, now: datetime | None = None) -> float:
    from athena.core.models import UsageEvent
    return float(session.execute(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0))
                                 .where(UsageEvent.created_at >= month_start(now))).scalar_one())


def month_tokens(session, user_id: UUID, now: datetime | None = None) -> int:
    from athena.core.models import UsageEvent
    total = UsageEvent.input_tokens + UsageEvent.output_tokens
    return int(session.execute(select(func.coalesce(func.sum(total), 0))
                               .where(UsageEvent.user_id == user_id,
                                      UsageEvent.created_at >= month_start(now))).scalar_one())


def _resets(now: datetime | None = None) -> str:
    return f"It resets on 1 {next_month(now):%B}."


def app_over_budget(session=None) -> bool:
    """Whether the app has spent this month's budget; background summaries pause once it has."""
    budget = budget_usd()
    if budget <= 0:
        return False
    if session is None:
        with _session() as own:
            return month_spend(own) >= budget
    return month_spend(session) >= budget


def refusal(user, session=None) -> str | None:
    """Why ``user`` may not start another model call this month, or None. Admins are never refused."""
    if user.role == "admin":
        return None
    budget, cap = budget_usd(), user_token_cap()
    if budget <= 0 and cap <= 0:
        return None
    own = session is None
    session = session or _session()
    try:
        if budget > 0 and month_spend(session) >= budget:
            return f"Athena has used this month's model budget. {_resets()} An admin can raise it."
        if cap > 0 and month_tokens(session, user.id) >= cap:
            return f"You have used this month's {cap:,} tokens. {_resets()}"
        return None
    finally:
        if own:
            session.close()


# ── alerts ─────────────────────────────────────────────────────────────


def budget_alerts(session, now: datetime | None = None) -> int | None:
    """Tell every admin, once a month each, when spending passes 80% and then 100% of the budget.

    Returns the threshold announced, or None. The caller commits.
    """
    from athena.core.config_store import set_setting
    from athena.core.models import User
    from athena.database import inbox

    now = now or datetime.now(timezone.utc)
    budget = budget_usd()
    if budget <= 0:
        return None
    spent = month_spend(session, now)
    reached = [t for t in ALERT_THRESHOLDS if spent >= budget * t / 100]
    if not reached:
        return None
    marker = ALERT_MARKER.format(month=f"{now:%Y-%m}")
    try:
        announced = int(get_setting(marker) or 0)
    except ValueError:
        announced = 0
    threshold = reached[-1]
    if threshold <= announced:
        return None
    if threshold >= 100:
        title = f"This month's model budget is used up (${spent:,.2f} of ${budget:,.2f})"
        body = "Users other than admins can't start model calls, and background summaries are paused. " + _resets(now)
    else:
        title = f"{threshold}% of this month's model budget is used (${spent:,.2f} of ${budget:,.2f})"
        body = "Past the budget, users other than admins can't start model calls and background summaries pause."
    admins = session.execute(select(User.id).where(User.role == "admin", User.is_active.is_(True))).scalars().all()
    for admin_id in admins:
        inbox.add_event(session, "budget", title, body, link="/settings/usage", user_id=admin_id,
                        payload={"threshold": threshold, "spent": round(spent, 4), "budget": budget})
    set_setting(marker, str(threshold))
    return threshold


# ── reports ────────────────────────────────────────────────────────────


def _since(days: int | None, now: datetime) -> datetime:
    from datetime import timedelta
    return month_start(now) if days is None else now - timedelta(days=days)


def _rows(session, columns, since: datetime, *where):
    from athena.core.models import UsageEvent
    tokens = func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens)
    stmt = (select(*columns, func.sum(UsageEvent.calls), func.sum(UsageEvent.input_tokens),
                   func.sum(UsageEvent.output_tokens), func.sum(UsageEvent.cost_usd))
            .where(UsageEvent.created_at >= since, *where).group_by(*columns).order_by(tokens.desc()))
    return [{"key": row[:-4], "calls": int(row[-4] or 0), "input_tokens": int(row[-3] or 0),
             "output_tokens": int(row[-2] or 0), "cost_usd": round(float(row[-1] or 0), 6)}
            for row in session.execute(stmt).all()]


def _totals(rows: list[dict]) -> dict:
    return {field: (round(sum(r[field] for r in rows), 6) if field == "cost_usd" else sum(r[field] for r in rows))
            for field in ("calls", "input_tokens", "output_tokens", "cost_usd")}


def _by_feature(rows: list[dict]) -> list[dict]:
    return [{"feature": r["key"][0], "label": FEATURES.get(r["key"][0], r["key"][0])}
            | {k: v for k, v in r.items() if k != "key"} for r in rows]


def user_report(session, user_id: UUID, now: datetime | None = None) -> dict:
    """One user's model use this month, by feature."""
    from athena.core.models import UsageEvent
    flush()
    now = now or datetime.now(timezone.utc)
    rows = _rows(session, [UsageEvent.feature], month_start(now), UsageEvent.user_id == user_id)
    cap = user_token_cap()
    totals = _totals(rows)
    return {"month": f"{now:%Y-%m}", "resets_at": next_month(now).isoformat(), "totals": totals,
            "features": _by_feature(rows),
            "token_cap": cap or None, "tokens_used": totals["input_tokens"] + totals["output_tokens"]}


def app_report(session, days: int | None = None, now: datetime | None = None) -> dict:
    """The whole app's model use: this month (or the last ``days`` days) by feature, model and user, and by day."""
    from athena.core.models import UsageEvent, User
    flush()
    now = now or datetime.now(timezone.utc)
    since = _since(days, now)
    features = _rows(session, [UsageEvent.feature], since)
    models = _rows(session, [UsageEvent.kind, UsageEvent.model], since)
    users = _rows(session, [UsageEvent.user_id], since)
    names = {u.id: u for u in session.execute(
        select(User).where(User.id.in_([r["key"][0] for r in users if r["key"][0] is not None]))).scalars()}
    day = func.date(UsageEvent.created_at)
    daily = session.execute(
        select(day, func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), func.sum(UsageEvent.cost_usd))
        .where(UsageEvent.created_at >= since).group_by(day).order_by(day)).all()

    def person(user_id) -> dict:
        user = names.get(user_id)
        if user_id is None:
            return {"user_id": None, "name": "Background", "email": None}
        return {"user_id": str(user_id), "name": user.display_name if user else "Deleted account",
                "email": user.email if user else None}

    budget = budget_usd()
    spent = month_spend(session, now)
    return {
        "since": since.isoformat(), "month": f"{now:%Y-%m}", "resets_at": next_month(now).isoformat(),
        "totals": _totals(features),
        "budget_usd": budget or None, "month_spend_usd": round(spent, 6),
        "over_budget": budget > 0 and spent >= budget,
        "user_token_cap": user_token_cap() or None,
        "features": _by_feature(features),
        "models": [{"kind": r["key"][0], "model": r["key"][1]} | {k: v for k, v in r.items() if k != "key"}
                   for r in models],
        "users": [person(r["key"][0]) | {k: v for k, v in r.items() if k != "key"} for r in users],
        "daily": [{"day": str(d), "tokens": int(t or 0), "cost_usd": round(float(c or 0), 6)} for d, t, c in daily],
    }
