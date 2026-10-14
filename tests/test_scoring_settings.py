"""Settings → Scoring (ROADMAP P1): every weight per category, saved as ScoringConfig versions, admins only."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import ContentCategory, SavedList, ScoringConfig, User, UserSession
from athena.pipeline.scoring import DEFAULT_WEIGHTS, _get_weights
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

pytestmark = pytest.mark.real_auth


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, ScoringConfig):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    redis = FakeRedis()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    with patch("athena.api.routers.app_settings._queue_rescore") as rescore:
        yield admin, Session, redis, rescore
    app.dependency_overrides.clear()


def weights(**changes) -> dict:
    base = {k: v for k, v in DEFAULT_WEIGHTS["paper"].items()}
    return base | changes


def test_defaults_until_saved(env):
    admin, *_ = env
    body = admin.get("/api/v1/settings/scoring").json()
    assert set(body["categories"]) == {"paper", "company_blog", "community_blog"}
    paper = body["categories"]["paper"]
    assert paper["source"] == "default" and paper["version"] is None and paper["preference"] == 0.3


def test_signal_weights_must_add_up_to_one(env):
    admin, *_ = env
    bad = admin.put("/api/v1/settings/scoring", json={"categories": {"paper": weights(citation=0.5)}})
    assert bad.status_code == 422 and "add up to 1.200" in bad.json()["detail"]
    assert admin.put("/api/v1/settings/scoring",
                     json={"categories": {"paper": weights(preference=0.9)}}).status_code == 422
    assert admin.put("/api/v1/settings/scoring",
                     json={"categories": {"video": weights()}}).status_code == 400


def test_a_change_is_a_new_version_and_rescores(env):
    admin, Session, _, rescore = env
    first = admin.put("/api/v1/settings/scoring",
                      json={"categories": {"paper": weights(citation=0.20, recency=0.30)}}).json()
    assert first["rescoring"] is True and rescore.call_count == 1
    assert first["categories"]["paper"]["source"] == "saved" and first["categories"]["paper"]["version"] == 1
    assert first["categories"]["company_blog"]["source"] == "default"
    second = admin.put("/api/v1/settings/scoring",
                       json={"categories": {"paper": weights(citation=0.25, recency=0.25)}}).json()
    assert second["categories"]["paper"]["version"] == 2
    with Session() as s:
        rows = s.execute(select(ScoringConfig.version, ScoringConfig.is_active).order_by(ScoringConfig.version)).all()
        assert rows == [(1, False), (2, True)]
        assert _get_weights("paper", s)["citation"] == 0.25


def test_an_unchanged_category_is_not_saved_again(env):
    admin, Session, _, rescore = env
    body = admin.put("/api/v1/settings/scoring", json={"categories": {"paper": weights()}}).json()
    assert body["rescoring"] is False and rescore.call_count == 0
    with Session() as s:
        assert s.query(ScoringConfig).count() == 0


def test_the_preference_weight_only_reorders_for_you(env):
    admin, Session, redis, rescore = env
    body = admin.put("/api/v1/settings/scoring", json={"categories": {"paper": weights(preference=0.5)}}).json()
    assert body["rescoring"] is False and rescore.call_count == 0
    assert redis.get("pref:ver:global") == 1
    with Session() as s:
        assert _get_weights("paper", s)["preference"] == 0.5
        assert s.query(ScoringConfig).one().category == ContentCategory.PAPER


def test_users_cannot_change_weights(env):
    admin, *_ = env
    _, bo = make_user(admin)
    assert bo.get("/api/v1/settings/scoring").status_code == 403
    assert bo.put("/api/v1/settings/scoring", json={"categories": {"paper": weights()}}).status_code == 403
