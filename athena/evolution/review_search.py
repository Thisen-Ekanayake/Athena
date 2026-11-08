"""
Sources for a literature review that no map covers (feedback 2026-11-07, problems 2 and 3).

The first version searched once with the user's whole question, put up to 8 library items first and wrote from
whatever came back. A 30-word question about NLLB hallucinations then got 2026 feed items and a 2014 SMT paper, and
none of the papers that define the area. Now:

1. **Plan.** The model turns the question into a few short searches (the names a researcher would type: "HalOmi",
   "hallucination neural machine translation") and the distinct parts the review must cover. Without the model,
   the question is split at its commas and conjunctions (``rule_concepts``).
2. **Search.** Semantic Scholar for every search, arXiv for the first two, Athena's library for the question.
3. **Rank** every paper by how close its title and abstract are to the question (the embedding model). Library
   papers get no head start, so the month's feed does not crowd out older work.
4. **Snowball** one hop: the references and citers of the best few cited papers, ranked the same way. One hop from
   any 2023 paper on the topic reaches the papers it builds on.
5. **Floor.** Papers below ``RELEVANCE_FLOOR`` are not sources. Each part of the question is then checked against
   the sources nearest to it, by the model (``coverage.judge``: similarity alone calls every MT paper "about"
   hallucination in MT), so the review can say what it found nothing on.

Without the embedding model the ranking falls back to word overlap with the question and its parts.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from loguru import logger

from athena.search.merger import _normalise_title, interleave, relevant_local, title_match

MAX_QUERIES = 6
MAX_CONCEPTS = 8
S2_PER_QUERY = 20
ARXIV_QUERIES = 2
ARXIV_PER_QUERY = 10
LIBRARY_PAPERS = 20
SNOWBALL_SEEDS = 5
SNOWBALL_MIN_CITATIONS = 10   # a seed must be cited this often, so its neighbours are worth fetching
SNOWBALL_PER_SEED = 100       # references, and as many citers
POOL_MAX = 500
EMBED_BATCH = 32
DOC_CHARS = 1500
PLAN_TOKENS = 600
# Cosine between the question (embedded as a query, with INSTRUCT) and a paper's title and abstract, with
# Qwen3-Embedding at 1024 dimensions. On the NLLB hallucination question (2026-11-08, 420 papers): the papers that
# define the area 0.75-0.80, other MT error and filtering work 0.70-0.75, MT classics (BLEU, the Transformer,
# seq2seq) 0.60-0.68, unrelated papers the snowball brought in under 0.45.
RELEVANCE_FLOOR = 0.65
LEXICAL_FLOOR = 0.35          # without the embedding model: the share of the question's words a paper has
CITATION_WEIGHT = 0.01        # per factor of ten citations, to break near-ties toward the established paper
TITLE_WEIGHT = 0.05           # per level of title_match: a paper the question names leads its neighbours
INSTRUCT = "Given a research question, retrieve titles and abstracts of papers that address it"
CONCEPT_INSTRUCT = "Given a research topic, retrieve titles and abstracts of papers about it"
NEAREST = 6                   # sources shown to the judge per part of the question

S2_FIELDS = "paperId,title,abstract,year,authors,citationCount,url,venue,externalIds"
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "e", "eg", "etc", "for", "from", "g", "how",
    "i", "ie", "in", "into", "is", "it", "its", "of", "on", "or", "such", "that", "the", "their", "them", "these",
    "this", "to", "via", "vs", "what", "when", "which", "who", "why", "with", "about", "between", "using", "use",
}
# Parts of a question every review covers anyway; checking them against sources says nothing.
GENERIC = {"open gaps", "gaps", "open problems", "open questions", "challenges", "future directions", "future work",
           "survey", "overview", "literature review", "review", "state of the art", "trends", "recent advances",
           "recent work", "limitations", "current state"}

Chat = Callable[[list[dict], int], tuple[str, int, int]]


@dataclass
class Plan:
    queries: list[str]
    concepts: list[str]
    by_model: bool = False
    subject: str = ""     # what the question is about, in a few words ("failure modes of NLLB-200")


@dataclass
class Found:
    papers: list[dict]                    # every paper ranked, best first, each with "relevance"
    sources: list[dict]                   # those at or above the floor
    concepts: dict[str, float]            # part of the question -> best score of a source against it
    queries: list[str] = field(default_factory=list)
    searched: int = 0                     # papers looked at
    method: str = "meaning"               # or "words" without the embedding model
    judged: bool = False                  # the parts' coverage was judged by the model

    @property
    def uncovered(self) -> list[str]:
        from athena.evolution.coverage import STRICT_FLOOR
        floor = 0.5 if self.judged else STRICT_FLOOR if self.method == "meaning" else LEXICAL_FLOOR
        return [c for c, score in self.concepts.items() if score < floor]


# ── the plan ─────────────────────────────────────────────────────────


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w\-]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 1]


def rule_concepts(query: str) -> list[str]:
    """The question's parts, split at punctuation and conjunctions: "NLLB-200: hallucination, omission and
    repetition; repair of translated data" -> NLLB-200, hallucination, omission, repetition, repair of translated
    data. Generic parts ("open gaps") are left out."""
    text = re.sub(r"\b(?:e\.g\.|i\.e\.|eg\.|such as|for example|including)\s*", ", ", query, flags=re.I)
    parts = re.split(r"[,;:()\[\]/]|\s+(?:and|or|vs\.?|versus)\s+|\?", text)
    out: list[str] = []
    for part in parts:
        part = re.sub(r"^\s*(?:the|a|an|of|on|in|for|how|what|which|why)\s+", "", part.strip(" .-"), flags=re.I)
        if not words(part) or _normalise_title(part) in GENERIC:
            continue
        if _normalise_title(part) not in {_normalise_title(o) for o in out}:
            out.append(part)
    return out[:MAX_CONCEPTS]


def head(query: str) -> str:
    """The question up to its first colon, semicolon or bracket: "X: a, b and c" is about X."""
    return re.split(r"[:;(]", query)[0].strip() or query


def rule_plan(query: str) -> Plan:
    concepts = rule_concepts(query)
    first = head(query)
    queries = [query] if len(query.split()) <= 8 else [" ".join(words(first)[:8])] if words(first) else []
    queries += [c for c in concepts if c not in queries]
    return Plan(queries=[q for q in queries if q][:MAX_QUERIES], concepts=concepts or [query], subject=first)


def plan_messages(query: str) -> list[dict]:
    return [{"role": "system", "content": "You plan literature searches for researchers. Answer with JSON only."},
            {"role": "user", "content": (
                f"Research question: {query}\n\n"
                'Return {"subject": "...", "queries": [...], "concepts": [...]}.\n'
                "subject: what the question is about, in 2 to 8 words, leaving out anything it names only as an "
                "example (\"failure modes of multilingual machine translation\" for a question on those that "
                "mentions one language as an example).\n"
                "queries: 3 to 6 short keyword searches (2 to 6 words each) that a researcher would type into "
                "Semantic Scholar to find the papers that define this area. Use the field's own names for the "
                "methods, models, benchmarks and phenomena involved, and keep each search on the question's "
                "subject (\"hallucination neural machine translation\", not just \"hallucination\").\n"
                "concepts: the 3 to 8 distinct parts of the question that a review of it must cover, each 2 to 8 "
                "words and understandable on its own (\"hallucination in machine translation\", not "
                "\"hallucination\"). Leave out generic parts such as \"open problems\".")}]


def parse_plan(text: str) -> Plan | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None

    def strings(key: str, limit: int) -> list[str]:
        items = data.get(key) if isinstance(data, dict) else None
        out = []
        for item in items or []:
            if isinstance(item, str) and words(item) and _normalise_title(item) not in GENERIC \
                    and item.strip() not in out:
                out.append(item.strip()[:120])
        return out[:limit]

    queries, concepts = strings("queries", MAX_QUERIES), strings("concepts", MAX_CONCEPTS)
    subject = data.get("subject") if isinstance(data.get("subject"), str) else ""
    return Plan(queries, concepts, by_model=True, subject=subject.strip()[:120]) if queries and concepts else None


def make_plan(query: str, chat: Chat | None) -> Plan:
    """The model's searches and parts of the question, or the rules' when it cannot give them."""
    if chat is not None:
        try:
            text, *_ = chat(plan_messages(query), PLAN_TOKENS)
            if (found := parse_plan(text)) is not None:
                found.subject = found.subject or head(query)
                return found
            logger.warning(f"Review plan: the model's answer was not usable: {text[:200]!r}")
        except Exception as exc:
            logger.warning(f"Review plan: the model did not answer: {exc}")
    return rule_plan(query)


# ── searching ────────────────────────────────────────────────────────


def s2_paper(raw: dict) -> dict | None:
    """A Semantic Scholar record in the search results' shape, or None without a title and abstract."""
    abstract = (raw.get("abstract") or "").strip()
    if not raw.get("title") or not abstract:
        return None
    ext = raw.get("externalIds") or {}
    return {"id": raw.get("paperId") or "", "title": raw["title"].strip(), "abstract": abstract,
            "url": raw.get("url"), "year": raw.get("year"),
            "authors": [a.get("name") for a in raw.get("authors") or [] if isinstance(a, dict) and a.get("name")],
            "citation_count": int(raw.get("citationCount") or 0), "venue": raw.get("venue") or None,
            "doi": (ext.get("DOI") or "").lower() or None, "arxiv_id": ext.get("ArXiv"),
            "source": "semantic_scholar"}


class Searcher:
    """The live searches, behind one Semantic Scholar client (its shared rate limit and patience)."""

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from athena.core.semantic_scholar import SemanticScholarClient
            self._client = SemanticScholarClient(cache_dir="", patience=60.0)
        return self._client

    def s2(self, query: str, limit: int = S2_PER_QUERY) -> list[dict]:
        try:
            raw = self.client.search(query, limit=limit, fields=S2_FIELDS)
        except Exception as exc:
            logger.warning(f"Review search: Semantic Scholar failed for {query!r}: {exc}")
            return []
        return [p for p in (s2_paper(r) for r in raw if isinstance(r, dict)) if p]

    def arxiv(self, query: str, limit: int = ARXIV_PER_QUERY) -> list[dict]:
        from athena.search.arxiv_live import search_arxiv
        return [p for p in search_arxiv(query, limit=limit) if p.get("abstract")]

    def library(self, query: str, limit: int = LIBRARY_PAPERS) -> list[dict]:
        from athena.search.local import search_local
        return [p for p in relevant_local(search_local(query, limit=limit), query) if p.get("abstract")]

    def neighbours(self, paper_id: str, limit: int = SNOWBALL_PER_SEED) -> list[dict]:
        """A paper's references and citers."""
        out = []
        for path, key in (("references", "citedPaper"), ("citations", "citingPaper")):
            try:
                data = self.client._request("GET", f"/paper/{paper_id}/{path}",
                                            {"fields": S2_FIELDS, "limit": limit}) or {}
            except Exception as exc:
                logger.warning(f"Review search: {path} of {paper_id} not fetched: {exc}")
                continue
            out += [p for p in (s2_paper(row.get(key) or {}) for row in data.get("data") or []) if p]
        return out


def _dedupe(papers: list[dict], seen: set[str] | None = None) -> list[dict]:
    seen = set() if seen is None else seen
    out = []
    for p in papers:
        key = _normalise_title(p.get("title"))
        if key and key not in seen:
            seen.add(key)
            out.append(p)
    return out


# ── ranking ──────────────────────────────────────────────────────────


Embed = Callable[[list[str], str | None], np.ndarray]


def model_embed(user_id=None) -> Embed:
    from athena.core import llm

    def embed(texts: list[str], instruct: str | None) -> np.ndarray:
        out = [llm.embed(texts[i:i + EMBED_BATCH], instruct=instruct, feature="lit_review", user_id=user_id)
               for i in range(0, len(texts), EMBED_BATCH)]
        return np.vstack(out) if out else np.zeros((0, 0))
    return embed


def document(p: dict) -> str:
    return f"{p.get('title') or ''}\n{p.get('abstract') or ''}"[:DOC_CHARS]


def overlap(text: str, have: set[str]) -> float:
    """The share of ``text``'s words found in ``have``."""
    wanted = set(words(text))
    return round(sum(1 for w in wanted if w in have) / len(wanted), 4) if wanted else 0.0


class Ranker:
    """Scores papers against the question and its parts: by meaning when the embedding model answers, else words."""

    def __init__(self, query: str, concepts: list[str], embed: Embed | None):
        self.query, self.concepts, self.embed = query, concepts, embed
        self.method = "words"
        self._query_vec = self._concept_vecs = None
        if embed is not None:
            try:
                self._query_vec = embed([query], INSTRUCT)[0]
                # Without the question as context: with it, every part scored like the question (0.6-0.85).
                self._concept_vecs = embed(concepts, CONCEPT_INSTRUCT) if concepts else None
                self.method = "meaning"
            except Exception as exc:
                logger.warning(f"Review search: no embedding model, ranking by words: {exc}")
        self._docs: dict[str, np.ndarray] = {}

    def _vectors(self, papers: list[dict]) -> None:
        todo = [p for p in papers if _normalise_title(p.get("title")) not in self._docs]
        if not todo:
            return
        vecs = self.embed([document(p) for p in todo], None)
        for p, v in zip(todo, vecs):
            self._docs[_normalise_title(p.get("title"))] = v

    def score(self, papers: list[dict]) -> None:
        """Sets each paper's "relevance" and "concepts" (its score against each part of the question)."""
        if self.method == "meaning":
            try:
                self._vectors(papers)
            except Exception as exc:
                logger.warning(f"Review search: embedding the papers failed, ranking by words: {exc}")
                self.method = "words"
        for p in papers:
            if self.method == "meaning":
                vec = self._docs[_normalise_title(p.get("title"))]
                p["relevance"] = round(float(np.dot(vec, self._query_vec)), 4)
                p["concepts"] = [round(float(np.dot(vec, c)), 4) for c in self._concept_vecs] \
                    if self._concept_vecs is not None else []
            else:
                have = set(words(document(p)))
                p["relevance"] = overlap(self.query, have)
                p["concepts"] = [overlap(c, have) for c in self.concepts]
            # A paper the question names leads; the citation prior only breaks near-ties.
            p["rank"] = p["relevance"] + TITLE_WEIGHT * title_match(self.query, p.get("title")) \
                + CITATION_WEIGHT * math.log10(1 + (p.get("citation_count") or 0))

    @property
    def floor(self) -> float:
        return RELEVANCE_FLOOR if self.method == "meaning" else LEXICAL_FLOOR


def find_sources(query: str, chat: Chat | None = None, embed: Embed | None = None, searcher: Searcher | None = None,
                 limit: int = 20, progress: Callable[[str], None] | None = None, plan: Plan | None = None) -> Found:
    """The papers an abstracts review is written from: planned searches, ranked by relevance, one snowball hop."""
    say = progress or (lambda label: None)
    searcher = searcher or Searcher()
    if plan is None:
        say("Planning the searches")
        plan = make_plan(query, chat)
    logger.info(f"Review search: queries {plan.queries}, concepts {plan.concepts} (model: {plan.by_model})")

    say("Searching Semantic Scholar, arXiv and the library")
    seen: set[str] = set()
    s2 = [searcher.s2(q) for q in plan.queries]
    arxiv = [searcher.arxiv(q) for q in plan.queries[:ARXIV_QUERIES]]
    pool = _dedupe(interleave(*s2, *arxiv) + searcher.library(query), seen)[:POOL_MAX]

    say("Ranking the papers")
    ranker = Ranker(query, plan.concepts, embed)
    ranker.score(pool)
    pool.sort(key=lambda p: -p["rank"])

    seeds = [p for p in pool if p.get("source") == "semantic_scholar" and p.get("id")
             and p["relevance"] >= ranker.floor and (p.get("citation_count") or 0) >= SNOWBALL_MIN_CITATIONS]
    if seeds:
        say("Following the best papers' references and citers")
        extra = _dedupe([n for s in seeds[:SNOWBALL_SEEDS] for n in searcher.neighbours(s["id"])], seen)
        extra = extra[:max(0, POOL_MAX - len(pool))]
        ranker.score(extra)
        pool = sorted(pool + extra, key=lambda p: -p["rank"])

    sources = [p for p in pool if p["relevance"] >= ranker.floor][:limit]
    concepts = {c: max((p["concepts"][i] for p in sources if i < len(p.get("concepts") or [])), default=0.0)
                for i, c in enumerate(plan.concepts)}
    judged = False
    if chat is not None and sources and plan.concepts:
        from athena.evolution.coverage import judge
        say("Checking which parts of the question the papers cover")
        near = {c: [(p["concepts"][i], p["title"]) for p in sorted(
            sources, key=lambda p: -(p["concepts"][i] if i < len(p.get("concepts") or []) else 0))[:NEAREST]]
            for i, c in enumerate(plan.concepts)}
        if (verdicts := judge("the papers a literature search found", query, near, chat)) is not None:
            concepts, judged = verdicts, True
    logger.info(f"Review search: {len(pool)} papers, {len(sources)} at or above {ranker.floor} ({ranker.method}); "
                f"parts {concepts} (judged: {judged})")
    return Found(papers=pool, sources=sources, concepts=concepts, queries=plan.queries, searched=len(pool),
                 method=ranker.method, judged=judged)
