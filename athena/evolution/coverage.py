"""
How much of a question a map covers (feedback 2026-11-07, problem 1).

A review asked about NLLB-200's hallucinations, omissions and tokenizer problems, and named Sinhala once as an
example. The name match ("sinhala" is an alias of the Sinhala NLP map) sent it to that map, and the review came out
about Sinhala POS tagging and Kaldi. The worker now checks a proposed map before writing from it:

- the question's subject (the review plan's, or the question up to its colon) must name the map: its name, an
  alias or a keyword (``names_map``). The NLLB question's subject, "failure modes of multilingual NMT", does not;
- and the model must not say the question is about another subject that only mentions the map's field
  (``about_field``). Alone, the model was swayed by wording: with the map's stored description ("…dedicated to
  analyzing, processing, and generating the Sinhala language") it called the NLLB question Sinhala NLP 7 times
  in 8;
- for a map review, and for a review from search results, the parts of the question nothing covers are named:

1. The parts are the review plan's concepts (``review_search.make_plan``: self-contained phrases such as
   "hallucination in neural machine translation"), or the question split by the rules.
2. For each part, the map papers nearest to it (their abstract vectors in Qdrant ``paper_abstracts``).
3. The model names, part by part, the paper among those whose title shows it studies that part, or none
   (``judge``). Similarity alone cannot decide: measured on
   2026-11-08, "hallucination in neural machine translation" scores 0.80 against the Sinhala NLP map (many MT
   papers, one on hallucination), "omission errors in NMT" 0.71 (none on it), its own subjects 0.82-0.90. The
   judge is lenient too: it found something for 5 of the NLLB question's 6 parts, which is why it only names
   what is missing and does not choose the map.

Without the chat model, the map is used when it covers at least ``MIN_SHARE`` of the parts, a part being covered
when its nearest paper scores at least ``STRICT_FLOOR``; without the embedding model, when it names the map or most
of its words are in one of the map's titles.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.evolution.review_search import rule_concepts, words

MIN_SHARE = 0.6        # a map grounds a review when it covers at least this share of the question's parts
NEAREST = 6            # map papers shown to the judge per part
STRICT_FLOOR = 0.75    # without the judge: cosine of a part to the map's nearest abstract (own subjects 0.82-0.90)
TITLE_SHARE = 0.75     # without either model: a part's words that must appear in one map title
JUDGE_TOKENS = 400
FIELD_TOKENS = 20
QUERY_INSTRUCT = "Given a research topic, retrieve titles and abstracts of papers about it"

Chat = Callable[[list[dict], int], tuple[str, int, int]]


@dataclass
class Coverage:
    parts: dict[str, float]       # part of the question -> 1 covered or 0 (judged), else its best score
    method: str                   # "judged", "meaning" or "words"
    nearest: dict[str, list[str]] = field(default_factory=dict)   # part -> titles of the map's nearest papers

    @property
    def floor(self) -> float:
        return {"judged": 0.5, "meaning": STRICT_FLOOR}.get(self.method, TITLE_SHARE)

    @property
    def covered(self) -> list[str]:
        return [p for p, s in self.parts.items() if s >= self.floor]

    @property
    def uncovered(self) -> list[str]:
        return [p for p, s in self.parts.items() if s < self.floor]

    @property
    def share(self) -> float:
        return len(self.covered) / len(self.parts) if self.parts else 1.0


def embed_parts(parts: list[str], timeout: float = 15.0):
    """The parts as query vectors in the map collections' space, or None when no embedding endpoint answers."""
    import numpy as np

    from athena.core import usage
    from athena.evolution import vectors
    from athena.evolution.classify import auth_headers, embed_model_name, embed_url
    from athena.model_server import activity
    url = embed_url()
    try:
        with activity.track("search", embed_model_name(), kind="embed") as call:
            resp = httpx.post(f"{url}/v1/embeddings", timeout=timeout, headers=auth_headers(url), json={
                "input": [f"Instruct: {QUERY_INSTRUCT}\nQuery: {p}" for p in parts], "model": embed_model_name()})
            resp.raise_for_status()
            call.tokens(usage.tokens_of(resp.json().get("usage"))[0])
    except httpx.HTTPError:
        return None
    usage.add("search", embed_model_name(), usage.tokens_of(resp.json().get("usage"))[0], kind="embed")
    rows = sorted(resp.json()["data"], key=lambda d: d["index"])
    return vectors.truncate(np.asarray([d["embedding"] for d in rows]))


def nearest(session: Session, topic, parts: list[str]) -> dict[str, list[tuple[float, str]]] | None:
    """For each part, the map's nearest papers as (score, title), or None without the embedding model."""
    from qdrant_client.http import models as qm

    from athena.core.models import EvoPaper, EvoTopicPaper
    from athena.evolution import vectors
    vecs = embed_parts(parts)
    if vecs is None:
        return None
    qdrant = vectors.client()
    if not qdrant.collection_exists(vectors.ABSTRACT_COLLECTION):
        return None
    titles = {str(pid): title for pid, title in session.execute(
        select(EvoPaper.id, EvoPaper.title).join(EvoTopicPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic.id)).all()}
    if not titles:
        return {p: [] for p in parts}
    only = qm.Filter(must=[qm.FieldCondition(key="paper_id", match=qm.MatchAny(any=list(titles)))])
    out = {}
    for part, vec in zip(parts, vecs):
        hits = qdrant.query_points(vectors.ABSTRACT_COLLECTION, query=vec.tolist(), query_filter=only,
                                   limit=NEAREST, with_payload=True).points
        out[part] = [(round(float(h.score), 4), titles.get(h.payload.get("paper_id"), "?")) for h in hits]
    return out


def judge_messages(collection: str, query: str, near: dict[str, list[tuple[float, str]]]) -> list[dict]:
    listed = "\n\n".join(f"P{i}: {part}\n" + ("\n".join(f"  - {title}" for _, title in near[part]) or "  (none)")
                         for i, part in enumerate(near, start=1))
    return [{"role": "system", "content": "You check whether research papers study given subjects, from their "
                                          "titles. You are strict. Answer with JSON only."},
            {"role": "user", "content": (
                f"Question: {query}\n\nThe papers are {collection}. For each part of the question, the papers "
                f"closest to it:\n\n{listed}\n\nFor each part, copy the title of the one listed paper whose title "
                "shows it studies that part itself, or answer \"none\". A paper on the wider field does not count: a "
                "general machine translation paper does not study omission errors, and a tokenizer paper does not "
                "study repairing translated datasets. Answer {\"P1\": \"<exact title>\" or \"none\", ...}.")}]


def judge(collection: str, query: str, near: dict[str, list[tuple[float, str]]], chat: Chat
          ) -> dict[str, float] | None:
    """1 for each part the model names a listed paper for, 0 for the others; None when its answer cannot be read.

    Asked for yes or no, the 9B said yes to every part of the NLLB question against the Sinhala NLP map ("omission
    errors in NMT" <- "Thinking Like Humans: A New Approach to Machine Translation"). Asked to name the paper, it
    must point at one, and a title it did not copy from the list does not count.
    """
    try:
        text, *_ = chat(judge_messages(collection, query, near), JUDGE_TOKENS)
    except Exception as exc:
        logger.warning(f"Map coverage: the model did not answer: {exc}")
        return None
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", text or "", flags=re.S), flags=re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        logger.warning(f"Map coverage: the model's answer was not usable: {text[:200]!r}")
        return None
    out = {}
    for i, part in enumerate(near, start=1):
        named = _key(str(data.get(f"P{i}") or ""))
        out[part] = 1.0 if named and any(_key(t) == named for _, t in near[part]) else 0.0
    return out


def _key(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", title.lower()).split())


def field_messages(topic, query: str) -> list[dict]:
    about = f" ({topic.description[:300]})" if getattr(topic, "description", None) else ""
    return [{"role": "system", "content": "You decide which source answers a research question best. Answer with one "
                                          "word."},
            {"role": "user", "content": (
                f"A research map collects the papers of one field: “{topic.name}”{about}.\n\nQuestion: {query}\n\n"
                "Is the question about this field, so that the map's papers are the right place to answer it "
                "(\"field\")? Or is it about a different subject that only mentions the field, for example as an "
                "example, a language or an application, so that most of the papers needed are outside it "
                "(\"other\")? Answer field or other.")}]


def about_field(topic, query: str, chat: Chat) -> bool | None:
    """Whether ``query`` asks about the map's field, or None when the model's answer cannot be read.

    Asked part by part, the 9B found the Sinhala NLP map covering most of the NLLB question; asked this, it answered
    "other" for it and "field" for Sinhala MT, POS tagging and LLMs, and for LoRA rank against PEFT (8 of 8
    questions on 2026-11-08, without thinking; with thinking it took a minute a question and twice said nothing).
    """
    try:
        text, *_ = chat(field_messages(topic, query), FIELD_TOKENS)
    except Exception as exc:
        logger.warning(f"Map choice: the model did not answer: {exc}")
        return None
    answer = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip().lower()
    if answer.startswith("field") or answer.startswith('"field'):
        return True
    if answer.startswith("other") or answer.startswith('"other'):
        return False
    logger.warning(f"Map choice: the model's answer was not usable: {text[:100]!r}")
    return None


def names_map(subject: str, topic) -> bool:
    """Whether the question's subject names the map: its name, an alias or a keyword (word-start match, as for
    paper relevance). "Failure modes of NLLB-200 and multilingual NMT" names nothing of the Sinhala NLP map."""
    from athena.evolution.corpus import relevance
    names = [topic.name, *(topic.aliases or []), *((topic.config or {}).get("keywords") or [])]
    return relevance(subject, None, [n.lower() for n in names if n]) > 0


def by_words(session: Session, topic, parts: list[str]) -> dict[str, float]:
    from athena.core.models import EvoPaper, EvoTopicPaper
    from athena.evolution.corpus import relevance
    names = [topic.name, *(topic.aliases or []), *((topic.config or {}).get("keywords") or [])]
    titles = [set(words(t)) for t in session.execute(
        select(EvoPaper.title).join(EvoTopicPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic.id)).scalars()]
    out = {}
    for part in parts:
        wanted = set(words(part))
        named = relevance(part, None, [n.lower() for n in names]) > 0 and len(wanted) <= 2
        best = max((len(wanted & t) / len(wanted) for t in titles), default=0.0) if wanted else 0.0
        out[part] = 1.0 if named else round(best, 4)
    return out


def check(session: Session, topic, query: str, chat: Chat | None = None, parts: list[str] | None = None) -> Coverage:
    """Which parts of ``query`` the map ``topic`` covers: judged by the model when ``chat`` is given."""
    parts = parts or rule_concepts(query) or [query]
    try:
        near = nearest(session, topic, parts)
    except Exception as exc:  # Qdrant down: the words still answer
        logger.warning(f"Map coverage: nearest papers not found: {exc}")
        near = None
    if near is None:
        return Coverage(by_words(session, topic, parts), "words")
    titles = {p: [t for _, t in hits] for p, hits in near.items()}
    if chat is not None and (judged := judge(f"those of the research map “{topic.name}”", query, near, chat)
                             ) is not None:
        return Coverage(judged, "judged", titles)
    return Coverage({p: hits[0][0] if hits else 0.0 for p, hits in near.items()}, "meaning", titles)
