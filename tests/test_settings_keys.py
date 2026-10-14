"""Settings → Keys: a key from the environment file shows as set, and a saved key overrides it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core.models import AppSetting


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AppSetting.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def keys(client) -> dict:
    return {k["key"]: k for k in client.get("/api/v1/settings/keys").json()}


def test_a_key_in_the_environment_shows_as_set(client, monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "abcd1234efgh5678")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    got = keys(client)
    assert got["SEMANTIC_SCHOLAR_API_KEY"] == {
        "key": "SEMANTIC_SCHOLAR_API_KEY", "masked_value": "abcd••••••••5678", "is_set": True, "updated_at": None,
        "source": "environment"}
    assert got["LLM_API_KEY"]["is_set"] is False and got["LLM_API_KEY"]["source"] is None


def test_a_saved_key_overrides_the_environment(client, monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "abcd1234efgh5678")
    assert client.post("/api/v1/settings/keys/SEMANTIC_SCHOLAR_API_KEY", json={"value": "zzzz0000yyyy9999"}).json()[
        "source"] == "database"
    got = keys(client)["SEMANTIC_SCHOLAR_API_KEY"]
    assert (got["source"], got["masked_value"]) == ("database", "zzzz••••••••9999")
    client.delete("/api/v1/settings/keys/SEMANTIC_SCHOLAR_API_KEY")
    assert keys(client)["SEMANTIC_SCHOLAR_API_KEY"]["source"] == "environment"
