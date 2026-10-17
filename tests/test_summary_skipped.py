"""Summaries skipped for too little text (ROADMAP_v2 T3): their own status, kept out of the queues, shown to admins."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core.models import (
    ContentCategory, ContentItem, JobType, PromptVersion, Source, SourceCategory, SourceType, SummaryStatus,
)
from athena.pipeline import scoring
from athena.pipeline import summarisation_tasks as st


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Source, ContentItem, PromptVersion):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(st, "SessionLocal", factory)
    monkeypatch.setattr(scoring, "SessionLocal", factory)
    with factory() as s:
        s.add(PromptVersion(job_type=JobType.ITEM_SUMMARY, version=1, system_prompt="s", user_prompt_tpl="u",
                            is_active=True))
        s.commit()
    return factory


def add(s, source_name="OpenAI News", status=SummaryStatus.PENDING, extra=None):
    source = s.query(Source).filter_by(name=source_name).first()
    if source is None:
        source = Source(id=uuid4(), name=source_name, url=f"https://{uuid4().hex}.example/feed", type=SourceType.RSS,
                        category=SourceCategory.COMPANY)
        s.add(source)
    item = ContentItem(id=uuid4(), source_id=source.id, title="t", url=f"https://example.org/{uuid4()}",
                       published_at=datetime(2026, 10, 10, tzinfo=timezone.utc), category=ContentCategory.COMPANY_BLOG,
                       content_hash=uuid4().hex, summary_status=status, extra_data=extra or {})
    s.add(item)
    s.commit()
    return item.id


def test_too_little_text_is_skipped_not_failed(Session, monkeypatch):
    monkeypatch.setattr(st, "check_budget_before_call", lambda *a, **k: True)
    monkeypatch.setattr(st, "_text_to_summarise", lambda item, staged: None)
    with Session() as s:
        item_id = add(s)
    st.summarise_item_worker(item_id)  # Celery passes a string; SQLite needs the UUID itself
    with Session() as s:
        item = s.get(ContentItem, item_id)
        assert item.summary_status == SummaryStatus.SKIPPED
        assert item.extra_data["summary_skipped"] == "too little text"


def test_rescoring_leaves_a_skipped_item_alone(Session, monkeypatch):
    queued = []
    monkeypatch.setattr(st.summarise_item_worker, "apply_async", lambda **kw: queued.append(kw))
    with Session() as s:
        item_id = add(s, status=SummaryStatus.SKIPPED, extra={"summary_skipped": "too little text"})
    scoring.enqueue_summary_tier(str(item_id), 0.9)
    scoring.enqueue_summary_tier(str(item_id), 0.1)
    with Session() as s:
        assert s.get(ContentItem, item_id).summary_status == SummaryStatus.SKIPPED
    assert queued == []


def test_admins_see_skipped_items_by_source_and_reason(Session):
    with Session() as s:
        for _ in range(3):
            add(s, status=SummaryStatus.SKIPPED, extra={"summary_skipped": "too little text"})
        add(s, "Hugging Face Blog", status=SummaryStatus.SKIPPED, extra={"summary_skipped": "too little text"})
        add(s, "Hugging Face Blog", status=SummaryStatus.COMPLETE)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    try:
        body = TestClient(app).get("/api/v1/admin/summaries/status").json()
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert body["counts"] == {"pending": 0, "complete": 1, "failed": 0, "lazy": 0, "skipped": 4}
    assert body["skipped"] == [{"source": "OpenAI News", "reason": "too little text", "count": 3},
                               {"source": "Hugging Face Blog", "reason": "too little text", "count": 1}]
