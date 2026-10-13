"""Usage and cost (ROADMAP R1): recording model calls, the monthly budget and token cap, alerts and the routes."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core import llm, usage
from athena.core.models import AppSetting, UsageEvent, User
from tests.conftest import ADMIN
from tests.fakes import FakeRedis

OCT = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
REAL_WRITE = usage._write  # kept before the conftest fixture swaps in a collector
USER = SimpleNamespace(id=uuid4(), email="bo@example.com", display_name="Bo", role="user", is_active=True,
                       must_change_password=False)


@pytest.fixture
def settings(monkeypatch):
    """Settings for usage and pricing, instead of the settings table."""
    values: dict[str, str] = {}
    lookup = lambda key, default="": values.get(key, default)  # noqa: E731
    monkeypatch.setattr(usage, "get_setting", lookup)
    monkeypatch.setattr(llm, "get_setting", lookup)
    return values


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (User.__table__, UsageEvent.__table__, AppSetting.__table__):
        table.create(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(usage, "_session", Session)
    return Session


def event(session, tokens=(100, 50), cost=0.0, user_id=None, when=OCT, feature="qa", model="m", kind="chat"):
    session.add(UsageEvent(created_at=when, user_id=user_id, feature=feature, kind=kind, model=model, calls=1,
                           input_tokens=tokens[0], output_tokens=tokens[1], cost_usd=cost))
    session.commit()


# ── recording ────────────────────────────────────────────────────────


def test_a_call_someone_made_is_written_at_once_and_priced(settings, usage_rows):
    settings.update(LLM_PRICE_IN_PER_M="2", LLM_PRICE_OUT_PER_M="8")
    usage.add("map_qa", "gpt", 1_000_000, 500_000, user_id=USER.id)
    assert len(usage_rows) == 1
    row = usage_rows[0]
    assert (row["feature"], row["model"], row["user_id"], row["calls"]) == ("map_qa", "gpt", USER.id, 1)
    assert row["cost_usd"] == pytest.approx(6.0)


def test_background_calls_are_summed_into_one_row_per_feature_and_model(settings, usage_rows):
    for _ in range(3):
        usage.add("map_build", "qwen", 10, 2)
    usage.add("map_embed", "emb", 40, kind="embed")
    assert usage_rows == []  # written within the minute, not per call
    usage.flush()
    rows = {r["feature"]: r for r in usage_rows}
    assert rows["map_build"]["calls"] == 3 and rows["map_build"]["input_tokens"] == 30
    assert rows["map_build"]["output_tokens"] == 6 and rows["map_build"].get("user_id") is None
    assert rows["map_embed"]["kind"] == "embed" and rows["map_embed"]["input_tokens"] == 40


def test_embeddings_have_their_own_price(settings):
    settings.update(LLM_PRICE_IN_PER_M="5", EMBED_PRICE_PER_M="0.02")
    assert llm.cost(1_000_000, 0, "embed") == pytest.approx(0.02)
    assert llm.cost(1_000_000, 0) == pytest.approx(5.0)


def test_recording_never_breaks_the_call(settings, usage_rows):
    with patch.object(llm, "cost", side_effect=RuntimeError("bad price")):
        usage.add("qa", "m", 1, 1, user_id=USER.id)  # no exception
    assert usage_rows == []


def test_rows_reach_the_database(db):
    REAL_WRITE([{"feature": "qa", "kind": "chat", "model": "m", "calls": 1, "input_tokens": 1, "output_tokens": 2,
                 "cost_usd": 0.0, "created_at": OCT}])
    with db() as s:
        assert s.query(UsageEvent).one().output_tokens == 2


def test_a_failed_write_is_logged_not_raised(monkeypatch):
    def broken():
        raise RuntimeError("database down")
    monkeypatch.setattr(usage, "_session", broken)
    REAL_WRITE([{"feature": "qa"}])  # no exception


@pytest.mark.parametrize("given,expected", [
    (None, (0, 0)),
    ({"prompt_tokens": 12, "completion_tokens": 3}, (12, 3)),
    ({"prompt_tokens": 7, "total_tokens": 7}, (7, 0)),          # embeddings
    (SimpleNamespace(prompt_tokens=5, completion_tokens=None), (5, 0)),
])
def test_token_counts_from_any_usage_shape(given, expected):
    assert usage.tokens_of(given) == expected


def test_months_turn_over_in_december():
    assert usage.month_start(OCT) == datetime(2026, 10, 1, tzinfo=timezone.utc)
    new_year = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert usage.next_month(datetime(2026, 12, 31, 23, tzinfo=timezone.utc)) == new_year


# ── the month's spend and the limits ─────────────────────────────────


def test_month_sums_leave_out_last_month(db):
    with db() as s:
        event(s, cost=1.5, user_id=USER.id)
        event(s, tokens=(10, 0), cost=0.25)
        event(s, cost=9.0, user_id=USER.id, when=datetime(2026, 9, 30, 23, tzinfo=timezone.utc))
        assert usage.month_spend(s, OCT) == pytest.approx(1.75)
        assert usage.month_tokens(s, USER.id, OCT) == 150


def test_no_budget_and_no_cap_refuse_nobody(settings, db):
    with db() as s:
        event(s, cost=100.0, user_id=USER.id, when=datetime.now(timezone.utc))
    assert usage.refusal(USER) is None


def test_past_the_budget_users_are_refused_and_admins_are_not(settings, db):
    settings["MONTHLY_BUDGET_USD"] = "2"
    with db() as s:
        event(s, cost=2.5, when=datetime.now(timezone.utc))
    assert "this month's model budget" in usage.refusal(USER)
    assert usage.refusal(ADMIN) is None
    assert usage.app_over_budget() is True


def test_past_the_token_cap_only_that_user_is_refused(settings, db):
    settings["USER_MONTHLY_TOKENS"] = "1000"
    other = SimpleNamespace(**{**vars(USER), "id": uuid4()})
    with db() as s:
        event(s, tokens=(900, 200), user_id=USER.id, when=datetime.now(timezone.utc))
    assert "1,000 tokens" in usage.refusal(USER)
    assert usage.refusal(other) is None


def test_the_allowance_check_refuses_with_the_monthly_reason():
    with patch.object(usage, "refusal", return_value="You have used this month's 1,000 tokens."):
        with pytest.raises(HTTPException) as exc:
            auth.use(FakeRedis(), USER, "qa")
    assert exc.value.status_code == 429 and "this month" in exc.value.detail


def test_allowances_show_todays_use(settings):
    redis = FakeRedis()
    with patch.object(auth, "get_setting", lambda key, default="": ""):
        auth.use(redis, USER, "idea_check")
        rows = {a["action"]: a for a in auth.allowances(redis, USER)}
        assert rows["idea_check"] == {"action": "idea_check", "label": "idea checks", "used": 1, "limit": 20}
        assert rows["map_qa_tokens"]["limit"] == 150_000
        assert all(a["limit"] is None for a in auth.allowances(redis, ADMIN))


# ── alerts ───────────────────────────────────────────────────────────


@pytest.fixture
def alerts(settings, db):
    """Admins to tell, and the inbox entries they got."""
    with db() as s:
        s.add_all([User(id=ADMIN.id, email="a@x.io", display_name="A", password_hash="-", role="admin"),
                   User(id=USER.id, email="b@x.io", display_name="B", password_hash="-", role="user")])
        s.commit()
    with patch("athena.database.inbox.add_event") as add, \
            patch("athena.core.config_store.set_setting", side_effect=settings.__setitem__):
        yield add


def test_admins_hear_at_80_and_100_percent_once_a_month(settings, db, alerts):
    settings["MONTHLY_BUDGET_USD"] = "10"
    with db() as s:
        event(s, cost=7.0)
        assert usage.budget_alerts(s, OCT) is None
        event(s, cost=1.5)
        assert usage.budget_alerts(s, OCT) == 80
        assert usage.budget_alerts(s, OCT) is None  # not twice
        event(s, cost=2.0)
        assert usage.budget_alerts(s, OCT) == 100
    assert alerts.call_count == 2  # one admin, two thresholds
    kind, title = alerts.call_args.args[1:3]
    assert kind == "budget" and "used up" in title and alerts.call_args.kwargs["user_id"] == ADMIN.id
    assert settings["BUDGET_ALERT_2026-10"] == "100"


def test_no_budget_no_alerts(settings, db, alerts):
    with db() as s:
        event(s, cost=50.0)
        assert usage.budget_alerts(s, OCT) is None
    alerts.assert_not_called()


# ── reports and routes ───────────────────────────────────────────────


def test_the_app_report_groups_by_feature_model_person_and_day(settings, db):
    now = datetime.now(timezone.utc)
    with db() as s:
        s.add(User(id=USER.id, email="b@x.io", display_name="Bo", password_hash="-", role="user"))
        s.commit()
        event(s, tokens=(100, 20), cost=0.5, user_id=USER.id, when=now, feature="map_qa")
        event(s, tokens=(1000, 0), when=now, feature="feed_embed", kind="embed", model="emb")
        report = usage.app_report(s)
    assert report["totals"]["input_tokens"] == 1100 and report["totals"]["cost_usd"] == pytest.approx(0.5)
    assert [f["feature"] for f in report["features"]] == ["feed_embed", "map_qa"]  # most tokens first
    assert report["features"][1]["label"] == "Questions to maps"
    people = {p["name"]: p for p in report["users"]}
    assert people["Bo"]["input_tokens"] == 100 and people["Background"]["user_id"] is None
    assert {m["model"] for m in report["models"]} == {"m", "emb"}
    assert len(report["daily"]) == 1 and report["daily"][0]["tokens"] == 1120


@pytest.fixture
def client(db):
    redis = FakeRedis()

    def session():
        s = db()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app), redis
    app.dependency_overrides.clear()


def as_user():
    from athena.api.auth import active_user, current_user
    app.dependency_overrides[current_user] = lambda: USER
    app.dependency_overrides[active_user] = lambda: USER


def test_my_usage(settings, client, db):
    c, _ = client
    as_user()
    with db() as s:
        event(s, tokens=(300, 100), user_id=USER.id, when=datetime.now(timezone.utc), feature="idea_check")
    body = c.get("/api/v1/usage/me").json()
    assert body["tokens_used"] == 400 and body["features"][0]["label"] == "Idea checks"
    assert body["token_cap"] is None and body["budget_reached"] is False
    assert {a["action"] for a in body["allowances"]} >= {"qa", "map_qa", "map_qa_tokens"}


def test_only_admins_see_the_whole_app(settings, client):
    c, _ = client
    assert c.get("/api/v1/usage/summary").status_code == 200
    as_user()
    assert c.get("/api/v1/usage/summary").status_code == 403
    assert c.get("/api/v1/usage/settings").status_code == 403
    assert c.put("/api/v1/usage/settings", json={"values": {}}).status_code == 403


@pytest.mark.parametrize("values,status", [
    ({"MONTHLY_BUDGET_USD": "12.5", "USER_MONTHLY_TOKENS": "200000", "LIMIT_QA_PER_DAY": "50"}, 200),
    ({"MONTHLY_BUDGET_USD": "-1"}, 422),
    ({"USER_MONTHLY_TOKENS": "1.5"}, 422),
    ({"LIMIT_MAP_QA_TOKENS_PER_DAY": "lots"}, 422),
    ({"LLM_API_KEY": "sk-..."}, 400),
])
def test_usage_settings_are_checked(client, db, values, status):
    c, _ = client
    resp = c.put("/api/v1/usage/settings", json={"values": values})
    assert resp.status_code == status
    if status == 200:
        with db() as s:
            assert s.get(AppSetting, "MONTHLY_BUDGET_USD").value == "12.5"


def test_an_empty_value_goes_back_to_the_default(client, db):
    c, _ = client
    with db() as s:
        s.add(AppSetting(key="LIMIT_QA_PER_DAY", value="5"))
        s.commit()
    assert c.put("/api/v1/usage/settings", json={"values": {"LIMIT_QA_PER_DAY": " "}}).status_code == 200
    with db() as s:
        assert s.get(AppSetting, "LIMIT_QA_PER_DAY") is None
