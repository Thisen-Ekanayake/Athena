"""Summary spend (ROADMAP_v2 D2): /admin/summaries/cost reads usage_events, the one usage log."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core.models import UsageEvent


def test_cost_sums_summary_and_label_calls_from_usage_events():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    UsageEvent.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    with Session() as s:
        s.add_all([
            UsageEvent(feature="summary", model="qwen", calls=3, input_tokens=300, output_tokens=60, cost_usd=0.03),
            UsageEvent(feature="cluster_label", model="qwen", calls=1, input_tokens=50, output_tokens=5,
                       cost_usd=0.01),
            UsageEvent(feature="summary", model="qwen", calls=2, input_tokens=200, output_tokens=40, cost_usd=0.02,
                       created_at=now - timedelta(days=3)),
            UsageEvent(feature="qa", model="qwen", calls=1, input_tokens=900, output_tokens=90, cost_usd=0.5),
        ])
        s.commit()

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    try:
        body = TestClient(app).get("/api/v1/admin/summaries/cost").json()
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert body["today_spend_usd"] == 0.04
    assert body["7_day_spend_usd"] == 0.06
    assert sorted(body["breakdown"], key=lambda r: r["feature"]) == [
        {"feature": "cluster_label", "model": "qwen", "calls": 1, "input_tokens": 50, "output_tokens": 5},
        {"feature": "summary", "model": "qwen", "calls": 3, "input_tokens": 300, "output_tokens": 60},
    ]
