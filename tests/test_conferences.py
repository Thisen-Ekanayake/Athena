"""Conference proceedings: which Anthology volumes count, reading the XML, storing changes, citations and abstracts
from two sources, embedding into topics, rising terms, summaries, and the routes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.conferences import anthology, citations, embed, summaries, tasks, terms, topics
from athena.conferences import venues as V
from athena.core import llm
from athena.core.models import (
    ConfPaper, ConfSummary, ConfTerm, ConfTopic, ConfVolume, ConfVolumeVenue, ContentItem, Source,
)
from tests.fakes import FakeRedis

# ── which volumes count ───────────────────────────────────────────────


@pytest.mark.parametrize("vid, tags, venues", [
    ("2024.acl-long", ["acl"], ["acl"]),
    ("2024.findings-acl", ["findings"], ["acl"]),
    ("2023.findings-ijcnlp", ["findings"], ["aacl"]),
    ("P06-1", ["coling", "acl"], ["coling", "acl"]),
    ("2024.lrec-main", ["lrec", "coling"], ["coling"]),
    ("2024.conll-1", ["conll"], []),
])
def test_a_volume_counts_for_its_followed_venues(vid, tags, venues):
    assert V.volume_venues(vid, tags) == venues


@pytest.mark.parametrize("vid, title, tags, kind", [
    ("2024.acl-long", "Proceedings of ACL (Volume 1: Long Papers)", ["acl"], "main"),
    ("2024.acl-short", "Proceedings of ACL (Volume 2: Short Papers)", ["acl"], "main"),
    ("2024.acl-demos", "Proceedings of ACL (Volume 3: System Demonstrations)", ["acl"], None),
    ("2024.acl-srw", "Proceedings of ACL (Volume 4: Student Research Workshop)", ["acl", "ws"], None),
    ("2025.emnlp-industry", "Proceedings of EMNLP: Industry Track", ["emnlp"], None),
    ("2024.findings-emnlp", "Findings of the ACL: EMNLP 2024", ["findings"], "findings"),
    ("2024.tacl-1", "Transactions of the ACL, Volume 12", ["tacl"], "journal"),
    ("C10-2", "Coling 2010: Posters", ["coling"], "main"),
    ("N06-3", "Companion Volume: Doctoral Consortium", ["naacl"], None),
    ("W12-33", "Some ACL workshop", ["acl"], None),
])
def test_only_main_proceedings_findings_and_journals_count(vid, title, tags, kind):
    assert V.volume_kind(vid, title, tags, V.volume_venues(vid, tags)) == kind


def test_awards_rank_best_papers_first():
    assert V.award_rank([]) is None
    assert V.award_rank(["Best Paper Award"]) == 0
    assert V.award_rank(["ACL 2022 10-Year Test of Time"]) == 0
    assert V.award_rank(["Outstanding Paper"]) == 1
    assert V.award_rank(["Best Resource Paper Award"]) == 1
    assert V.award_rank(["SAC Award: Generation"]) == 2
    assert V.award_rank(["Honorable Mention for Best Long Paper"]) == 2
    assert V.award_rank(["SAC Highlight Award", "Outstanding Paper Award"]) == 1


@pytest.mark.parametrize("collection, volume, paper, pid", [
    ("2024.acl", "long", "12", "2024.acl-long.12"),
    ("P18", "1", "31", "P18-1031"),
    ("J98", "1", "2", "J98-1002"),
    ("C69", "10", "1", "C69-1001"),
    ("C69", "1", "1", "C69-0101"),
])
def test_anthology_ids(collection, volume, paper, pid):
    assert anthology.paper_id(collection, volume, paper) == pid


# ── reading and storing ───────────────────────────────────────────────

ACL_2024 = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2024.acl">
  <volume id="long" ingest-date="2024-08-01" type="proceedings">
    <meta><booktitle>Proceedings of the 62nd Annual Meeting (Volume 1: Long Papers)</booktitle>
      <year>2024</year><venue>acl</venue></meta>
    <frontmatter><url>2024.acl-long.0</url></frontmatter>
    <paper id="1">
      <title>Quantized <fixed-case>S</fixed-case>ide Tuning</title>
      <author><first>Zhihao</first><last>Zhang</last></author>
      <author><first>Qing</first><last>Li</last></author>
      <abstract>We tune <tex-math>4</tex-math>-bit models
        with a side network.</abstract>
      <doi>10.18653/v1/2024.acl-long.1</doi>
      <award name="Outstanding Paper Award"/>
    </paper>
    <paper id="2"><title>A Paper Without an Abstract</title><author><last>Solo</last></author></paper>
    <paper id="3"><title>Retracted Work</title><retracted date="2024-09-01">Retracted.</retracted></paper>
    <paper id="4"><title>Book Reviews: A Grammar Writer’s Cookbook</title></paper>
  </volume>
  <volume id="demos" type="proceedings">
    <meta><booktitle>Proceedings of the 62nd Annual Meeting (Volume 3: System Demonstrations)</booktitle>
      <year>2024</year><venue>acl</venue></meta>
    <paper id="1"><title>A Demo</title></paper>
  </volume>
</collection>"""

FINDINGS_2024 = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2024.findings">
  <volume id="acl" type="proceedings">
    <meta><booktitle>Findings of the ACL: ACL 2024</booktitle><year>2024</year><venue>findings</venue></meta>
    <paper id="7"><title>Findings Paper on Dialogue</title><author><first>A</first><last>B</last></author>
      <abstract>Dialogue systems that talk.</abstract></paper>
  </volume>
</collection>"""

P18 = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="P18">
  <volume id="1" type="proceedings">
    <meta><booktitle>Proceedings of the 56th Annual Meeting of the ACL (Volume 1: Long Papers)</booktitle>
      <year>2018</year><venue>acl</venue></meta>
    <paper id="31"><title>Universal Language Model Fine-tuning for Text Classification</title>
      <author><first>Jeremy</first><last>Howard</last></author><award name="ACL 2023 Test of Time Award"/></paper>
  </volume>
</collection>"""


@pytest.fixture
def xml_dir(tmp_path) -> Path:
    for name, text in (("2024.acl.xml", ACL_2024), ("2024.findings.xml", FINDINGS_2024), ("P18.xml", P18)):
        (tmp_path / name).write_text(text)
    return tmp_path


def test_reading_keeps_main_and_findings_and_cleans_text(xml_dir):
    volumes = {v.id: v for v in anthology.read_all(xml_dir)}
    assert set(volumes) == {"2024.acl-long", "2024.findings-acl", "P18-1"}
    long = volumes["2024.acl-long"]
    assert (long.year, long.kind, long.venues) == (2024, "main", ["acl"])
    # no frontmatter, retraction or book review
    assert [p.id for p in long.papers] == ["2024.acl-long.1", "2024.acl-long.2"]
    first = long.papers[0]
    assert first.title == "Quantized Side Tuning"
    assert first.abstract == "We tune 4-bit models with a side network."
    assert first.authors == ["Zhihao Zhang", "Qing Li"] and long.papers[1].authors == ["Solo"]
    assert first.awards == ["Outstanding Paper Award"] and first.doi == "10.18653/v1/2024.acl-long.1"
    assert volumes["2024.findings-acl"].venues == ["acl"] and volumes["2024.findings-acl"].kind == "findings"
    assert volumes["P18-1"].papers[0].id == "P18-1031"


@pytest.fixture
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Source, ContentItem, ConfVolume, ConfVolumeVenue, ConfTopic, ConfPaper, ConfTerm, ConfSummary):
        model.__table__.create(engine)
    return sessionmaker(bind=engine)


def test_storing_adds_changes_and_drops_papers(Session, xml_dir):
    with Session() as s:
        stats = anthology.store(s, anthology.read_all(xml_dir))
        assert (stats["papers"], stats["new"], stats["removed"]) == (4, 4, [])
        assert s.get(ConfPaper, "2024.acl-long.1").award_rank == 1
        assert s.get(ConfPaper, "P18-1031").award_rank == 0
        assert s.get(ConfPaper, "2024.acl-long.1").abstract_from == "anthology"

        # An abstract found elsewhere stays; an embedded paper whose title changes is embedded again.
        found = s.get(ConfPaper, "2024.acl-long.2")
        found.abstract, found.abstract_from = "Found on OpenAlex.", "openalex"
        first = s.get(ConfPaper, "2024.acl-long.1")
        first.embedded_at, first.embed_model, first.topic_id = datetime.now(timezone.utc), "m", None
        s.commit()

    (xml_dir / "2024.acl.xml").write_text(ACL_2024.replace("Quantized <fixed-case>S</fixed-case>ide Tuning",
                                                           "Quantized Side Tuning, Revised"))
    (xml_dir / "P18.xml").unlink()
    with Session() as s:
        stats = anthology.store(s, anthology.read_all(xml_dir))
        assert stats["changed"] == 1 and stats["removed"] == ["P18-1031"]
        assert s.get(ConfPaper, "2024.acl-long.2").abstract == "Found on OpenAlex."
        first = s.get(ConfPaper, "2024.acl-long.1")
        assert first.title.endswith("Revised") and first.embedded_at is None
        assert s.get(ConfVolume, "P18-1") is None
        assert s.execute(select(ConfVolumeVenue.venue).where(
            ConfVolumeVenue.volume_id == "2024.findings-acl")).scalars().all() == ["acl"]


def test_the_tarball_is_read_without_git(tmp_path, monkeypatch):
    import io
    import tarfile

    import httpx
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in (("acl-anthology-master/data/xml/2024.acl.xml", ACL_2024),
                           ("acl-anthology-master/python/setup.py", "x")):
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, text="abc123")
        return httpx.Response(200, content=buf.getvalue())

    monkeypatch.setattr(anthology, "data_dir", lambda: tmp_path / "anthology")
    http = httpx.Client(transport=httpx.MockTransport(handler))
    xml_dir, changed = anthology.fetch(http=http)
    assert changed and [p.name for p in xml_dir.iterdir()] == ["2024.acl.xml"]
    assert anthology.fetch(http=http) == (xml_dir, False)  # same commit: not fetched again


# ── citations and abstracts ───────────────────────────────────────────


def _seed(Session, xml_dir):
    with Session() as s:
        anthology.store(s, anthology.read_all(xml_dir))


def test_citations_take_the_larger_count_and_fill_missing_abstracts(Session, xml_dir, monkeypatch):
    _seed(Session, xml_dir)
    monkeypatch.setattr(citations, "SessionLocal", Session)
    monkeypatch.setattr(citations, "_openalex", lambda papers: {"10.18653/v1/2024.acl-long.1": (40, None)})
    monkeypatch.setattr(citations, "_semantic_scholar", lambda papers: {
        "2024.acl-long.1": (55, None), "P18-1031": (4450, None),
        "2024.acl-long.2": (3, "An abstract that Semantic Scholar has for this paper, which is long enough to count.")})
    with Session() as s:
        p = s.get(ConfPaper, "2024.acl-long.2")
        p.embedded_at, p.embed_model = datetime.now(timezone.utc), "m"
        s.commit()
    stats = citations.refresh()
    assert stats["asked"] == 4 and stats["abstracts"] == 1
    with Session() as s:
        assert s.get(ConfPaper, "2024.acl-long.1").citation_count == 55
        assert s.get(ConfPaper, "P18-1031").citation_count == 4450
        filled = s.get(ConfPaper, "2024.acl-long.2")
        assert filled.abstract_from == "semantic_scholar" and filled.embedded_at is None
        assert s.get(ConfPaper, "2024.findings-acl.7").citations_at is not None  # asked, though unknown
    assert citations.refresh()["asked"] == 0  # nothing due again for a week


def test_citations_wait_when_both_sources_fail(Session, xml_dir, monkeypatch):
    _seed(Session, xml_dir)
    monkeypatch.setattr(citations, "SessionLocal", Session)

    def down(papers):
        raise RuntimeError("down")
    monkeypatch.setattr(citations, "_openalex", down)
    monkeypatch.setattr(citations, "_semantic_scholar", down)
    assert citations.refresh().get("failed")
    with Session() as s:
        assert s.execute(select(ConfPaper).where(ConfPaper.citations_at.is_not(None))).first() is None


# ── embedding and topics ──────────────────────────────────────────────


class FakeQdrant:
    def __init__(self):
        self.points = {}

    def collection_exists(self, name):
        return True

    def upsert(self, name, points):
        for p in points:
            self.points[p.id] = p

    def scroll(self, name, limit, offset=None, with_vectors=True, with_payload=True):
        from types import SimpleNamespace
        pts = [SimpleNamespace(payload=p.payload, vector=p.vector) for p in self.points.values()]
        return pts, None

    def delete(self, name, points_selector):
        for pid in points_selector.points:
            self.points.pop(pid, None)


def _axis(i: int) -> list[float]:
    v = np.zeros(llm.EMBED_DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def _fake_embed(texts, instruct=None, **kw):
    """Topics and papers on axes by keyword: dialogue → 0, everything else → 1."""
    return np.asarray([_axis(0 if "dialogue" in t.lower() else 1) for t in texts])


@pytest.fixture
def embedding(Session, xml_dir, monkeypatch):
    _seed(Session, xml_dir)
    with Session() as s:
        s.add_all([ConfTopic(name="Dialogue", description="dialogue systems", position=0),
                   ConfTopic(name="Efficient methods", description="quantization", position=1)])
        s.commit()
    fake = FakeQdrant()
    monkeypatch.setattr(embed, "SessionLocal", Session)
    monkeypatch.setattr(embed, "qdrant", lambda: fake)
    monkeypatch.setattr(embed, "ensure_collection", lambda: None)
    monkeypatch.setattr(llm, "embed", _fake_embed)
    monkeypatch.setattr(llm, "embed_model", lambda: "qwen3-embedding-8b")
    return fake


def test_embedding_sorts_papers_into_their_nearest_topic(Session, embedding):
    assert embed.run() == {"embedded": 4, "more": False}
    with Session() as s:
        dialogue, efficient = (t.id for t in s.execute(select(ConfTopic).order_by(ConfTopic.position)).scalars())
        assert s.get(ConfPaper, "2024.findings-acl.7").topic_id == dialogue
        assert s.get(ConfPaper, "2024.acl-long.1").topic_id == efficient
        assert s.get(ConfPaper, "2024.acl-long.1").topic_score == pytest.approx(1.0)
        assert s.get(ConfTopic, dialogue).vector_model == "qwen3-embedding-8b"
    assert len(embedding.points) == 4
    assert embed.run()["embedded"] == 0


def test_a_new_embedding_model_embeds_everything_again(Session, embedding, monkeypatch):
    embed.run()
    monkeypatch.setattr(llm, "embed_model", lambda: "another-embedder")
    assert embed.run()["embedded"] == 4


def test_editing_a_topic_sorts_stored_vectors_again(Session, embedding):
    embed.run()
    with Session() as s:
        dialogue = s.execute(select(ConfTopic).where(ConfTopic.name == "Dialogue")).scalar_one()
        dialogue.name, dialogue.description = "Everything", "quantization and the rest"
        topics.touch(dialogue)
        s.commit()
        assert topics.reassign_all(s) == 4
        # Both topics now sit where the non-dialogue papers are, and the first of them wins; the dialogue paper
        # is nearest neither and goes to the first too.
        assert {p.topic_id for p in s.execute(select(ConfPaper)).scalars()} == {dialogue.id}


def test_the_seed_list_is_written_once(Session):
    with Session() as s:
        assert topics.ensure_seeded(s) is True
        assert topics.ensure_seeded(s) is False
        assert len(topics.SEED) == len(s.execute(select(ConfTopic)).scalars().all()) >= 25


# ── terms ─────────────────────────────────────────────────────────────


def test_phrases_do_not_cross_punctuation_or_start_with_stopwords():
    got = terms.phrases("Large language models (LLMs) reason, and the agents plan.")
    assert "large language models" in got and "llms" in got and "agents plan" in got
    assert "models llms" not in got and "the agents" not in got and "and" not in got


def test_rising_terms_are_phrases_that_grew_since_the_previous_edition():
    before = [f"Statistical machine translation with phrases {i}" for i in range(60)]
    now = [f"Large language models as agents {i}" for i in range(40)] + before[:20]
    counts_now, counts_before = terms._counts(now), terms._counts(before)
    prior = counts_now + counts_before
    scores = terms.log_odds(counts_now, len(now), counts_before, len(before), prior, len(now) + len(before))
    rising = terms.pick(scores, counts_now, True, 5)
    falling = terms.pick(scores, counts_before, False, 5)
    assert any("large language models" in t for t in rising)
    assert "language" not in rising  # held by a longer phrase
    assert any("machine translation" in t for t in falling)


# ── the routes ────────────────────────────────────────────────────────


@pytest.fixture
def client(Session, embedding):
    embed.run()
    with Session() as s:
        s.get(ConfPaper, "2024.acl-long.2").citation_count = 90
        s.get(ConfPaper, "2024.acl-long.1").citation_count = 5
        s.add(ConfTerm(venue="acl", year=2024, term="side tuning", papers=1, share=0.3, prev_share=0.0, score=2.5))
        s.add(ConfSummary(venue="acl", year=2024, text="ACL 2024 was about tuning.", stats_hash="x"))
        s.commit()
    redis = FakeRedis()

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_redis, None)


def test_the_list_has_every_venue_and_the_topics(client):
    body = client.get("/api/v1/conferences").json()
    acl = next(v for v in body["venues"] if v["slug"] == "acl")
    assert acl["years"] == [2024, 2018] and acl["latest_papers"] == 3
    assert acl["editions"] == [{"year": 2018, "papers": 1}, {"year": 2024, "papers": 3}]
    assert acl["latest_kinds"] == {"main": 2, "findings": 1}
    assert [t["name"] for t in body["topics"]] == ["Dialogue", "Efficient methods"]
    assert body["progress"]["sorted"] == 4
    assert body["family"]["editions"] == [{"year": 2018, "papers": 1}, {"year": 2024, "papers": 3}]


def test_an_edition_has_shares_awards_terms_and_summary(client):
    view = client.get("/api/v1/conferences/acl").json()
    assert view["year"] == 2024 and view["previous_year"] == 2018 and view["papers"] == 3
    assert view["by_kind"] == {"main": 2, "findings": 1}
    shares = {t["name"]: t for t in view["topics"]}
    assert shares["Efficient methods"]["papers"] == 2 and shares["Dialogue"]["share"] == pytest.approx(1 / 3)
    assert shares["Efficient methods"]["prev_share"] == pytest.approx(1.0)  # 2018: the one paper
    assert [a["id"] for a in view["awards"]] == ["2024.acl-long.1"]
    assert view["terms"]["rising"][0]["term"] == "side tuning"
    assert view["summary"]["text"].startswith("ACL 2024")
    only_main = client.get("/api/v1/conferences/acl", params={"kinds": "main"}).json()
    assert only_main["papers"] == 2
    assert client.get("/api/v1/conferences/acl", params={"kinds": "posters"}).status_code == 422
    assert client.get("/api/v1/conferences/icml").status_code == 404
    assert client.get("/api/v1/conferences/eacl").status_code == 404


def test_top_papers_put_awards_before_citations(client):
    body = client.get("/api/v1/conferences/acl/papers", params={"year": 2024}).json()
    assert [p["id"] for p in body["papers"]] == ["2024.acl-long.1", "2024.acl-long.2", "2024.findings-acl.7"]
    assert body["total"] == 3
    every_year = client.get("/api/v1/conferences/all/papers").json()
    assert every_year["papers"][0]["id"] == "P18-1031"  # test of time outranks outstanding


def test_trends_and_comparison(client):
    trend = client.get("/api/v1/conferences/acl/trends").json()
    assert [y["year"] for y in trend["years"]] == [2018, 2024]
    assert sum(trend["years"][1]["topics"].values()) == 3
    both = client.get("/api/v1/conferences/compare", params={"venues": "acl,emnlp", "year": 2024}).json()
    assert [v["venue"] for v in both["venues"]] == ["acl"] and both["missing"] == ["emnlp"]


def test_a_paper_and_its_item(client, Session, monkeypatch):
    monkeypatch.setattr("athena.conferences.items._stage", lambda item, paper: None)
    monkeypatch.setattr(embed, "similar", lambda pid, limit=8: ["2024.acl-long.2"])
    paper = client.get("/api/v1/conferences/papers/2024.acl-long.1").json()
    assert paper["venues"] == [{"slug": "acl", "name": "ACL"}] and paper["kind"] == "main"
    assert paper["abstract"].startswith("We tune") and paper["similar"][0]["id"] == "2024.acl-long.2"
    first = client.post("/api/v1/conferences/papers/2024.acl-long.1/item").json()
    again = client.post("/api/v1/conferences/papers/2024.acl-long.1/item").json()
    assert first["made"] is True and again == {"item_id": first["item_id"], "made": False}
    with Session() as s:
        item = s.execute(select(ContentItem)).scalar_one()
        assert item.url == "https://aclanthology.org/2024.acl-long.1/" and item.source.is_active is False
    assert client.get("/api/v1/conferences/papers/nope").status_code == 404


def test_admins_edit_the_topic_list(client, Session, monkeypatch):
    resorts = []
    monkeypatch.setattr(tasks.reassign, "apply_async", lambda **kw: resorts.append(kw))
    before = tasks.version()
    added = client.post("/api/v1/conferences/topics", json={"name": "Speech", "description": "speech"})
    assert added.status_code == 201 and added.json()["position"] == 2
    assert client.post("/api/v1/conferences/topics", json={"name": "speech"}).status_code == 409
    tid = added.json()["id"]
    assert client.patch(f"/api/v1/conferences/topics/{tid}", json={"position": 0}).status_code == 200
    assert len(resorts) == 1  # moving it does not change what it means
    client.patch(f"/api/v1/conferences/topics/{tid}", json={"description": "spoken language"})
    with Session() as s:
        assert s.get(ConfTopic, tid).vector is None
    assert client.delete(f"/api/v1/conferences/topics/{tid}").status_code == 204
    assert len(resorts) == 3 and tasks.version() >= before


@pytest.mark.real_auth
def test_people_who_are_not_admins_cannot_edit_topics(client):
    from athena.api.auth import active_user
    from athena.core.models import User
    from uuid import uuid4
    member = User(id=uuid4(), email="m@example.com", display_name="M", password_hash="-", role="member",
                  is_active=True, must_change_password=False)
    app.dependency_overrides[active_user] = lambda: member
    try:
        assert client.post("/api/v1/conferences/topics", json={"name": "Nope"}).status_code == 403
        assert client.post("/api/v1/conferences/sync").status_code == 403
    finally:
        app.dependency_overrides.pop(active_user, None)


# ── summaries ─────────────────────────────────────────────────────────


def test_summaries_are_written_once_per_set_of_numbers(Session, embedding, monkeypatch):
    embed.run()
    monkeypatch.setattr(summaries, "SessionLocal", Session)
    monkeypatch.setattr(llm, "chat_model", lambda task=None: "qwen3.5-9b")
    asked = []

    def chat_json(prompt, schema, name, **kw):
        asked.append(prompt)
        return {"summary": "  It was about   tuning. "}, {}
    monkeypatch.setattr(llm, "chat_json", chat_json)
    stats = summaries.run()
    with Session() as s:
        rows = {(r.venue, r.year): r.text for r in s.execute(select(ConfSummary)).scalars()}
    assert ("all", 2024) not in rows  # fewer than 20 papers: not worth a summary
    assert stats == {"written": 0, "more": False} and not asked

    monkeypatch.setattr(summaries, "due", lambda session: [("acl", 2024)])
    assert summaries.run()["written"] == 1
    with Session() as s:
        assert s.get(ConfSummary, ("acl", 2024)).text == "It was about tuning."
    assert "ACL 2024" in asked[0] and "2018" in asked[0]


# ── the tasks ─────────────────────────────────────────────────────────


@pytest.fixture
def queued(monkeypatch):
    """Task calls queued rather than run, and a fake Redis for status and locks."""
    redis = FakeRedis()
    monkeypatch.setattr(tasks, "_redis", lambda: redis)
    sent = []
    for name in ("embed_papers", "write_summaries", "citations"):
        task = getattr(tasks, name)
        monkeypatch.setattr(task, "delay", lambda *a, _n=name: sent.append((_n, a)))
        monkeypatch.setattr(task, "apply_async",
                            lambda args=(), countdown=None, _n=name: sent.append((_n, tuple(args))))
    return sent


@pytest.mark.parametrize("asked, level", [(True, "routine"), (False, "backlog")])
def test_an_admins_sync_shares_the_gpu_with_the_feed(queued, monkeypatch, asked, level):
    from athena.model_server import turns
    seen = []
    monkeypatch.setattr(embed, "run", lambda deadline=None: seen.append(turns.NAMES[turns.priority_of("conf_embed")])
                        or {"embedded": 3, "more": False})
    tasks.embed_papers(asked)
    assert seen == [level] and queued == [("write_summaries", (asked,))]


def test_a_long_wait_for_the_gpu_is_not_called_a_pause(queued, monkeypatch):
    from athena.model_server import lane

    def held(deadline=None):
        raise lane.Paused("waited")
    monkeypatch.setattr(embed, "run", held)
    tasks.embed_papers(True)
    assert tasks.status()["stage"] == "waiting" and queued == [("embed_papers", (True,))]
    lane.pause("conferences")
    tasks.embed_papers(True)
    assert tasks.status()["stage"] == "paused"
    lane.resume("conferences")
