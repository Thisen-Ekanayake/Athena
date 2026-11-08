"""Literature reviews after the NLLB feedback (2026-11-07): planned searches ranked by relevance, the relevance floor,
the claim-citation check, and a map used only when it covers the question."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from athena.api.main import app
from athena.evolution import coverage, review_search, verify
from tests.test_auth import setup_admin
from tests.test_review import env  # noqa: F401  (fixture)

QUESTION = ("Failure modes of NLLB-200 and multilingual NMT for low-resource languages: hallucination, omission, "
            "repetition, tokenizer/script issues (e.g. Sinhala ZWJ loss); detection, mitigation, repair of "
            "machine-translated datasets; open gaps")


# ── the plan ─────────────────────────────────────────────────────────


def test_the_rules_split_a_question_into_its_parts():
    parts = review_search.rule_concepts(QUESTION)
    assert parts[:3] == ["Failure modes of NLLB-200", "multilingual NMT for low-resource languages", "hallucination"]
    assert "Sinhala ZWJ loss" in parts and "tokenizer" in parts
    assert not any("gaps" in p for p in parts)                      # generic parts are left out
    assert len(parts) == review_search.MAX_CONCEPTS


def test_the_models_plan_is_used_and_a_bad_answer_falls_back_to_the_rules():
    good = '<think>x</think>{"queries": ["NLLB hallucination", "HalOmi"], "concepts": ["hallucination", "open gaps"]}'
    plan = review_search.make_plan(QUESTION, lambda m, t: (good, 1, 1))
    assert plan.by_model and plan.queries == ["NLLB hallucination", "HalOmi"] and plan.concepts == ["hallucination"]
    fallback = review_search.make_plan(QUESTION, lambda m, t: ("no json here", 1, 1))
    assert not fallback.by_model
    assert fallback.queries[0] == "failure modes nllb-200 multilingual nmt low-resource languages"
    assert review_search.make_plan("graph rag", None).queries == ["graph rag"]


# ── finding sources ──────────────────────────────────────────────────


def paper(title, abstract, source="semantic_scholar", cites=0, pid=None):
    return {"id": pid or title, "title": title, "abstract": abstract, "year": 2023, "authors": ["A"],
            "citation_count": cites, "source": source}


class FakeSearcher:
    def __init__(self):
        self.asked, self.expanded = [], []

    def s2(self, query):
        self.asked.append(query)
        return [paper("Hallucinations in Large Multilingual Translation Models", "hallucination nmt", cites=200,
                      pid="guerreiro"),
                paper("Beam search for SMT", "beam statistical")]

    def arxiv(self, query):
        return [paper("HalOmi benchmark", "hallucination omission nmt", source="arxiv")]

    def library(self, query):
        return [paper("Multilingual LLM traces", "reasoning traces", source="local")]

    def neighbours(self, pid):
        self.expanded.append(pid)
        return [paper("The Curious Case of Hallucinations in NMT", "hallucination nmt", cites=300)]


def fake_embed(texts, instruct):
    """On-topic text (with "hallucination") points one way, everything else another."""
    def vec(t):
        v = np.array([1.0, 0.2]) if "hallucination" in t.lower() else np.array([0.1, 1.0])
        return v / np.linalg.norm(v)
    return np.array([vec(t) for t in texts])


def test_sources_are_ranked_by_relevance_snowballed_and_floored():
    searcher = FakeSearcher()
    plan = '{"queries": ["hallucination nmt", "omission"], "concepts": ["hallucination", "ZWJ loss"]}'
    judged = []

    def chat(messages, max_tokens):
        if "study given subjects" in messages[0]["content"]:
            judged.append(messages[-1]["content"])
            return '{"P1": "HalOmi benchmark", "P2": "none"}', 1, 1
        return plan, 1, 1
    found = review_search.find_sources("hallucination in NMT", chat, fake_embed, searcher)
    titles = [p["title"] for p in found.sources]
    assert searcher.asked == ["hallucination nmt", "omission"] and searcher.expanded == ["guerreiro"]
    assert "The Curious Case of Hallucinations in NMT" in titles             # reached by the snowball
    assert "Beam search for SMT" not in titles and "Multilingual LLM traces" not in titles   # below the floor
    assert found.method == "meaning" and found.searched == 5
    assert found.judged and found.uncovered == ["ZWJ loss"]                  # no source on it
    assert "P1: hallucination\n  - " in judged[0]                           # judged from the nearest sources


def test_without_the_embedding_model_words_rank_the_papers():
    def broken(texts, instruct):
        raise ConnectionError("no model server")
    found = review_search.find_sources("hallucination nmt", None, broken, FakeSearcher())
    assert found.method == "words"
    assert {p["title"] for p in found.sources} >= {"HalOmi benchmark",
                                                   "Hallucinations in Large Multilingual Translation Models"}
    assert "Multilingual LLM traces" not in {p["title"] for p in found.sources}


# ── the citation check ───────────────────────────────────────────────


def test_unsupported_citations_and_then_uncited_sentences_are_removed():
    text = ("Kaldi is a toolkit for speech recognition [1]. It also builds translation systems [1, 2].\n"
            "- NLLB covers 200 languages [3].\n"
            "Hallucinations are detected by similarity [4]. Plain sentence.")

    def chat(messages, max_tokens):
        content = messages[-1]["content"]
        out = {}
        for line in content.splitlines():
            if line.startswith("C"):
                key, claim = line.split(":", 1)
                bad = ("translation systems" in claim and "[1]" in claim) or "NLLB covers" in claim
                out[key] = "no" if bad else "partly" if "similarity" in claim else "yes"
        import json
        return json.dumps(out), 1, 1

    out, counts = verify.verify(text, {1: "Kaldi ASR toolkit.", 2: "MT system.", 3: "Toxicity.", 4: "Sim."}, chat)
    assert out == ("Kaldi is a toolkit for speech recognition [1]. It also builds translation systems [2].\n"
                   "Hallucinations are detected by similarity [4]. Plain sentence.")
    assert counts["no"] == 2 and counts["partly"] == 1 and counts["sentences_removed"] == 1


def test_an_unreadable_check_keeps_the_text():
    text = "A claim [1]."
    out, counts = verify.verify(text, {1: "Source."}, lambda m, t: ("I think it is fine", 1, 1))
    assert out == text and counts["unread"] == 1 and counts["checked"] == 0


# ── map coverage and the worker ──────────────────────────────────────


def test_coverage_counts_the_parts_a_map_covers():
    judged = coverage.Coverage({"hallucination in MT": 0.0, "Sinhala tokenization": 1.0, "omission": 0.5}, "judged")
    assert judged.covered == ["Sinhala tokenization", "omission"] and judged.uncovered == ["hallucination in MT"]
    assert judged.share == pytest.approx(2 / 3)
    strict = coverage.Coverage({"hallucination in NMT": 0.80, "Sinhala POS tagging": 0.90, "x": 0.6}, "meaning")
    assert strict.covered == ["hallucination in NMT", "Sinhala POS tagging"]


def test_the_model_judges_each_part_from_the_maps_nearest_papers(monkeypatch):
    topic = SimpleNamespace(id=uuid4(), name="Sinhala NLP", aliases=[], config={})
    near = {"hallucination in machine translation": [(0.80, "English to Sinhala NMT")],
            "Sinhala part-of-speech tagging": [(0.90, "A POS tagger for Sinhala")]}
    monkeypatch.setattr(coverage, "nearest", lambda s, t, parts: near)
    seen = []

    def chat(messages, max_tokens):
        seen.append(messages[-1]["content"])
        return '{"P1": "none", "P2": "A POS tagger for Sinhala."}', 1, 1
    c = coverage.check(None, topic, "q", chat, list(near))
    assert c.method == "judged" and c.uncovered == ["hallucination in machine translation"] and c.share == 0.5
    assert "  - English to Sinhala NMT" in seen[0] and "research map “Sinhala NLP”" in seen[0]
    unread = coverage.check(None, topic, "q", lambda m, t: ("no idea", 1, 1), list(near))
    assert unread.method == "meaning" and unread.share == 1.0     # falls back to the strict similarity floor
    invented = coverage.check(None, topic, "q", lambda m, t: ('{"P1": "Hallucinations in NMT", "P2": "none"}', 1, 1),
                              list(near))
    assert invented.share == 0.0                                  # a title not in the list does not count


def test_the_model_says_whether_a_question_is_about_the_maps_field():
    topic = SimpleNamespace(name="Sinhala NLP", description="Tools and models for Sinhala")
    assert coverage.about_field(topic, QUESTION, lambda m, t: ("other", 1, 1)) is False
    assert coverage.about_field(topic, "Sinhala POS tagging", lambda m, t: ("<think>x</think>Field.", 1, 1)) is True
    assert coverage.about_field(topic, "x", lambda m, t: ("maybe", 1, 1)) is None
    prompt = coverage.field_messages(topic, QUESTION)[-1]["content"]
    assert "“Sinhala NLP” (Tools and models for Sinhala)" in prompt and "Question: Failure modes" in prompt


def test_coverage_without_the_model_uses_names_and_titles(monkeypatch):
    topic = SimpleNamespace(id=uuid4(), name="Sinhala NLP", aliases=["sinhala"], config={"keywords": ["sinhala"]})
    titles = ["Sinhala part of speech tagging", "A Sinhala corpus"]
    session = SimpleNamespace(execute=lambda stmt: SimpleNamespace(scalars=lambda: titles))
    monkeypatch.setattr(coverage, "nearest", lambda *a: None)
    c = coverage.check(session, topic, "NLLB hallucination, omission and Sinhala tokenization")
    assert c.method == "words" and c.parts["Sinhala tokenization"] == 1.0 and c.parts["omission"] == 0.0
    assert c.share < coverage.MIN_SHARE


def test_a_map_that_only_shares_a_name_with_the_question_is_not_used(monkeypatch):
    """The route proposes the map; the worker finds it covers too little and writes from a search instead."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from athena.core.models import EvoTopic, LitReview, User
    from athena.evolution import review
    from tests.test_review import BUILT, is_check, verdicts
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, EvoTopic, LitReview):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("athena.database.db.SessionLocal", Session)
    with Session() as s:
        user = User(id=uuid4(), email="a@b.c", display_name="A", password_hash="-", role="admin")
        topic_id = uuid4()
        s.execute(EvoTopic.__table__.insert().values(id=topic_id, slug="sinhala-nlp", name="Sinhala NLP",
                                                     status="ready", aliases=None, seeds=None, config=None,
                                                     built_at=BUILT))
        s.add(user)
        s.flush()
        r = LitReview(user_id=user.id, topic_id=topic_id, query=QUESTION, title="t", mode="map")
        s.add(r)
        s.commit()
        rid = r.id
    thin = coverage.Coverage({"hallucination in MT": 0.0, "omission in MT": 0.0, "Sinhala script": 1.0}, "judged")
    papers = [{"id": str(i), "title": f"Hallucination paper {i}", "abstract": "Hallucinations in NMT.", "year": 2023}
              for i in range(6)]

    def chat(messages, max_tokens):
        return (verdicts(messages), 1, 1) if is_check(messages) else ("Hallucinations happen [1].", 1, 1)
    assert review.run(rid, chat=chat, papers=papers, coverage=thin)["status"] == "done"
    with Session() as s:
        done = s.get(LitReview, rid)
        assert done.mode == "abstracts" and done.topic_id is None
        assert "“Sinhala NLP” matched the question, but its papers cover only 1 of the question's 3 parts" \
            in done.markdown


@pytest.mark.real_auth
def test_the_route_keeps_the_question_as_the_title(env, monkeypatch):  # noqa: F811
    from athena.core.models import EvoTopic
    from athena.database import evolution as evo_db
    Session, _ = env
    with Session() as s:
        peft_id = s.query(EvoTopic).filter_by(slug="peft").one().id
    monkeypatch.setattr(evo_db, "find_topic", lambda s, q: s.get(EvoTopic, peft_id))
    admin = TestClient(app)
    setup_admin(admin)
    proposed = admin.post("/api/v1/reviews", json={"query": "LoRA rank choice"}).json()
    assert proposed["mode"] == "map" and proposed["topic"]["slug"] == "peft" and proposed["title"] == "LoRA rank choice"


def test_a_question_about_another_subject_is_written_from_a_search(monkeypatch):
    """The model's "other" sends the review to a search even when the map seems to cover the parts."""
    from types import SimpleNamespace as NS

    from athena.evolution import review
    monkeypatch.setattr(review, "map_covers", lambda *a: (None, False, coverage.Coverage({"a": 1.0}, "judged")))
    saved = {}
    topic = NS(name="Sinhala NLP", slug="sinhala-nlp", built_at=1)
    review_row = NS(mode="map", topic_id=uuid4(), query=QUESTION, status="queued", user_id=uuid4())

    class Session:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, model, key):
            return review_row if model.__name__ == "LitReview" else topic

        def commit(self):
            saved.update(vars(review_row))

        def rollback(self):
            pass
    monkeypatch.setattr("athena.database.db.SessionLocal", Session)
    papers = [{"id": str(i), "title": f"P{i}", "abstract": "Text.", "year": 2023} for i in range(5)]
    assert review.run(uuid4(), chat=lambda m, t: ("Text [1].", 1, 1), papers=papers)["status"] == "done"
    assert saved["mode"] == "abstracts" and "only mentions its field" in saved["markdown"]


def test_a_map_is_used_only_when_the_questions_subject_names_it():
    sinhala = SimpleNamespace(name="Sinhala Natural Language Processing", aliases=["Sinhala NLP", "sinhala"],
                              config={"keywords": ["sinhala", "speech recognition"]})
    assert not coverage.names_map("failure modes of multilingual neural machine translation", sinhala)
    assert coverage.names_map("English to Sinhala machine translation", sinhala)
    assert review_search.rule_plan(QUESTION).subject == \
        "Failure modes of NLLB-200 and multilingual NMT for low-resource languages"
    plan = review_search.parse_plan('{"subject": "failure modes of NLLB-200", "queries": ["nllb errors"], '
                                    '"concepts": ["omission errors"]}')
    assert plan.subject == "failure modes of NLLB-200"
