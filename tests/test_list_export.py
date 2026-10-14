"""Saved lists as BibTeX and RIS (ROADMAP S2): papers, blog posts, map data, your notes, and who may export."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import (
    ContentCategory, ContentItem, EvoPaper, InterestProfile, ItemFeedback, ItemRead, SavedList, SavedListItem, Source,
    SourceCategory, SourceType, User, UserHighlight, UserNote, UserSession,
)
from athena.database import library_export
from athena.evolution import export
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

pytestmark = pytest.mark.real_auth


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, SavedListItem, Source, ContentItem, EvoPaper, ItemRead, UserNote,
                  UserHighlight, ItemFeedback, InterestProfile):
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
    ids = {}
    with Session() as s:
        arxiv, blog = uuid4(), uuid4()
        s.execute(Source.__table__.insert().values(id=arxiv, name="ArXiv AI", url="https://export.arxiv.org",
                                                   type=SourceType.API, category=SourceCategory.PAPER,
                                                   fetch_config=None))
        s.execute(Source.__table__.insert().values(id=blog, name="OpenAI News", url="https://openai.com/news/rss",
                                                   type=SourceType.RSS, category=SourceCategory.COMPANY,
                                                   fetch_config=None))
        for name, source, category, url, authors in (
                ("lora", arxiv, ContentCategory.PAPER, "http://arxiv.org/abs/2106.09685v2", ["E. Hu", "Y. Shen"]),
                ("blog", blog, ContentCategory.COMPANY_BLOG, "https://openai.com/index/prompt-caching", None)):
            ids[name] = uuid4()
            title = "LoRA: Low-Rank Adaptation" if name == "lora" else "Prompt caching"
            s.execute(ContentItem.__table__.insert().values(
                id=ids[name], source_id=source, title=title, url=url, category=category, content_hash=name,
                published_at=datetime(2021, 6, 17, tzinfo=timezone.utc), authors=authors, extra_data={}))
        s.execute(EvoPaper.__table__.insert().values(
            id=uuid4(), openalex_id="W1", title="LoRA", year=2021, authors=["Edward J. Hu", "Yelong Shen"],
            authorships=None, merged_ids=None, extra=None, doi="10.48550/arxiv.2106.09685", venue="ICLR",
            arxiv_id="2106.09685", content_item_id=ids["lora"]))
        s.commit()
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    lst = admin.post("/api/v1/lists", json={"name": "Fine-tuning & caching ✨"}).json()
    for name in ("lora", "blog"):
        admin.post(f"/api/v1/lists/{lst['id']}/items", json={"item_id": str(ids[name])})
    yield admin, lst, ids, Session
    app.dependency_overrides.clear()


def test_a_list_exports_as_bibtex_with_map_data_and_notes(env):
    admin, lst, ids, _ = env
    admin.put(f"/api/v1/items/{ids['lora']}/note", json={"body": "Rank 8 was enough.\n\nCompare with DoRA."})
    admin.post(f"/api/v1/items/{ids['lora']}/highlights",
               json={"field": "summary", "quote": "low-rank", "comment": "key"})
    resp = admin.get(f"/api/v1/lists/{lst['id']}/export", params={"format": "bib"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/x-bibtex")
    disposition = resp.headers["content-disposition"]
    assert 'filename="fine-tuning-caching.bib"' in disposition and "filename*=UTF-8''Fine-tuning%20%26" in disposition
    bib = resp.text
    assert "@inproceedings{hu2021lora," in bib and "booktitle = {ICLR}" in bib
    assert "doi = {10.48550/arxiv.2106.09685}" in bib and "author = {Edward J. Hu and Yelong Shen}" in bib
    assert "annote = {Rank 8 was enough. \\par Compare with DoRA. \\par “low-rank” (key)}" in bib
    assert "@misc{openai2021prompt," in bib and "howpublished = {\\url{https://openai.com/index/prompt-caching}}" in bib
    assert "note = {OpenAI News}" in bib


def test_a_list_exports_as_ris(env):
    admin, lst, ids, _ = env
    admin.put(f"/api/v1/items/{ids['blog']}/note", json={"body": "Cheaper repeats"})
    ris = admin.get(f"/api/v1/lists/{lst['id']}/export", params={"format": "ris"}).text
    records = ris.strip().split("\n\n")
    blog = next(r for r in records if "Prompt caching" in r)
    assert blog.startswith("TY  - BLOG") and "PB  - OpenAI News" in blog and "N1  - Cheaper repeats" in blog
    assert "Y2  - " in blog
    paper = next(r for r in records if "LoRA" in r)
    assert paper.startswith("TY  - CONF") and "T2  - ICLR" in paper and "N1  - arXiv:2106.09685" in paper


def test_only_the_owner_exports_and_the_format_is_checked(env):
    admin, lst, _, _ = env
    _, bo = make_user(admin)
    assert bo.get(f"/api/v1/lists/{lst['id']}/export", params={"format": "bib"}).status_code == 404
    assert admin.get(f"/api/v1/lists/{lst['id']}/export", params={"format": "csv"}).status_code == 422
    empty = admin.post("/api/v1/lists", json={"name": "Empty"}).json()
    assert admin.get(f"/api/v1/lists/{empty['id']}/export", params={"format": "ris"}).text == ""


def test_feed_papers_without_a_map_keep_their_arxiv_id(env):
    _, lst, ids, Session = env
    with Session() as s:
        s.query(EvoPaper).delete()
        s.commit()
        user_id = s.query(User).one().id
        papers = library_export.list_papers(s, user_id, s.query(SavedList).one().id, today=date(2026, 10, 14))
    lora = next(p for p in papers if p["title"].startswith("LoRA"))
    assert lora["arxiv_id"] == "2106.09685" and lora["authors"] == ["E. Hu", "Y. Shen"] and "doi" not in lora
    blog = next(p for p in papers if p["title"] == "Prompt caching")
    assert blog["kind_hint"] == "online" and blog["accessed"] == "2026-10-14"
    assert export.cite_keys([blog]) == ["openai2021prompt"]
