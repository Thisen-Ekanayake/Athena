"""
Propose a topic from a search: its anchor papers, keywords, fields and name.

Curated topics are written by hand (scripts/seed_evolution_topics.py). A
search for anything else gets a proposal the person checks before building:

1. Fields: OpenAlex groups the papers matching the query by field; the
   largest fields covering 80% of them, at most three, become the topic's.
2. Candidates: the most-cited works with the query in the title, plus
   OpenAlex's semantic matches (papers that never use the query's words).
   Duplicate records of one paper (preprint and proceedings) are grouped, the
   most cited first, the rest kept as ``alt_ids`` as for curated seeds.
3. Anchors: the most-cited method paper in each third of the candidates'
   years, the most-cited overall, and at most one survey. Ranking by
   citations alone fills every slot with the oldest papers ("mixture of
   experts" gave three 1990s papers).
4. Keywords: the query and its spelling variants, plus acronyms the
   candidates define for it ("Mixture of Experts (MoE)"), quoted so they
   match only the whole word, and inflections the papers use ("mixtures of
   experts"). Other phrases ending in the query's last word that several
   papers use ("visual tracking") are offered, not ticked.

That costs three OpenAlex searches ($0.003). Then, if the 9B can run, it
picks anchors from the numbered candidates (it cannot name a paper that is
not listed) and writes keywords, aliases and a description
(``refine``); generic keywords it suggests are dropped.

Proposals live in Redis for a day. Nothing here needs the graph libraries, so
the API image can run it.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from athena.evolution.corpus import EXCLUDED_TYPES, classify_kind, relevance, title_key
from athena.evolution.openalex import OpenAlexClient, Work

if TYPE_CHECKING:
    from athena.evolution.classify import Classifier

FIELD_COVER = 0.8
MAX_FIELDS = 3
DEFAULT_FIELDS = ["Computer Science"]
TITLE_HITS = 50
TITLE_CANDIDATES = 22
SEMANTIC_CANDIDATES = 8
MAX_ANCHORS = 5
MAX_MERGED_ANCHORS = 6      # the 9B's picks plus rule picks from periods it left out
ANCHOR_GAP_YEARS = 5        # a rule pick this far from every 9B pick covers a period the 9B missed
MAX_KEYWORDS = 20
MAX_ALIASES = 8
SUGGESTION_MIN_PAPERS = 3
MAX_SUGGESTIONS = 8
REFINE_WAIT_SECONDS = 180   # the 9B must start within this, or the GPU is busy and the rules stand
PROPOSAL_TTL_SECONDS = 24 * 3600
REDIS_PREFIX = "evoprop:"   # outside the evo:{slug}:* keys that topic changes invalidate

# Words used across all of machine learning: as keywords they would make most of a corpus on-topic.
GENERIC = {
    "model", "models", "learning", "network", "networks", "neural", "neural network", "neural networks", "deep",
    "deep learning", "machine learning", "artificial intelligence", "ai", "transformer", "transformers",
    "attention", "fine-tun", "fine-tuning", "fine tuning", "finetuning", "training", "pretraining", "pre-training",
    "language model", "language models", "large language model", "large language models", "llm", "llms",
    "dataset", "datasets", "benchmark", "method", "methods", "approach", "algorithm", "algorithms", "framework",
    "optimization", "data", "performance", "efficient", "efficiency", "inference", "representation",
    "representations", "embedding", "embeddings", "classification", "prediction", "analysis", "system",
    "systems", "image", "images", "video", "vision", "computer vision", "nlp", "natural language processing",
    "generative", "generation", "task", "tasks", "accuracy", "evaluation", "architecture", "architectures",
}
_STOP = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "with", "to", "by", "via", "from", "using", "based",
         "is", "are", "as", "at", "its", "their", "this", "that", "we", "our", "new", "novel", "towards", "toward",
         "each", "every", "all", "any", "such", "other", "more", "most", "both", "these", "those", "which", "can",
         "may", "also", "not", "than", "then", "into", "over", "under", "between", "through", "during", "without",
         "within", "across", "multiple", "different", "various", "efficient", "fast", "accurate", "robust"}


@dataclass
class Candidate:
    openalex_id: str
    title: str
    year: int | None
    citations: int
    kind: str
    venue: str | None = None
    alt_ids: list[str] = field(default_factory=list)
    title_match: bool = False      # the title names the query (a word-start match)
    semantic: bool = False         # found by OpenAlex's semantic search
    abstract: str | None = None    # kept for keyword mining and the 9B; not sent to the browser

    def public(self) -> dict:
        out = asdict(self)
        out.pop("abstract")
        return out


# ── text helpers ───────────────────────────────────────────────────────


def clean_query(query: str) -> str:
    return " ".join(query.split())[:200]


def variants(query: str) -> list[str]:
    """'Mixture of Experts' -> ['mixture of experts', 'mixture-of-experts']; hyphens also become spaces."""
    q = clean_query(query).lower().replace('"', "")
    out = [q, q.replace("-", " ")]
    words = q.split()
    if 1 < len(words) <= 4 and "-" not in q:  # "mixture-of-experts"; an already hyphenated query has its form
        out.append("-".join(words))
    return [v for v in dict.fromkeys(out) if v]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "topic"


def topic_name(query: str) -> str:
    """Sentence case that keeps the person's capitals: 'object tracking' -> 'Object tracking', 'LoRA' stays."""
    q = clean_query(query)
    return q[:1].upper() + q[1:]


def quote_if_short(keyword: str) -> str:
    """Acronyms and other short single words match as whole words, so "mot" does not find "motion"."""
    k = keyword.strip()
    if k.startswith('"') and k.endswith('"'):
        return k
    return f'"{k}"' if len(k) <= 4 and re.fullmatch(r"[a-z0-9]+", k) else k


def lint_keywords(keywords: list[str], query: str) -> list[str]:
    """Lower-case, drop generic or empty ones (unless the query itself uses them), quote short ones.

    The last word loses a plural "s": keywords match at the start of a word, so "graph neural network"
    finds "networks" too, while "graph neural networks" would miss "The Graph Neural Network Model".
    """
    q = clean_query(query).lower()
    out = []
    for raw in keywords:
        k = " ".join(str(raw).lower().replace('"', " ").split())
        if len(k) < 2 or len(k.split()) > 5:
            continue
        if k in GENERIC and k not in q:
            continue
        words = k.split(" ")
        words[-1] = _stems([words[-1]])[0]
        out.append(quote_if_short(" ".join(words)))
    return list(dict.fromkeys(out))[:MAX_KEYWORDS]


def acronyms(query: str, texts: list[str]) -> list[str]:
    """Acronyms the papers define for the query: 'mixture of experts (MoE)' -> ['moe'], used twice or more."""
    # Spaces and hyphens are interchangeable, so every spelling variant gives the same pattern.
    words = re.split(r"[\s-]+", variants(query)[0])
    pattern = re.compile(r"[\s-]+".join(re.escape(w) for w in words) + r"s?\s*\(\s*([A-Za-z][A-Za-z0-9-]{1,9})\s*\)",
                         re.IGNORECASE)
    found: Counter = Counter()
    for text in texts:
        seen = set()
        for match in pattern.findall(text or ""):
            acr = match[:-1] if match.endswith("s") and match[:-1].isupper() else match
            if acr.isupper() or any(c.isupper() for c in acr[1:]):  # an acronym, not an ordinary word
                seen.add(acr.lower())
        found.update(seen)
    # Two letters ("sd") collide more easily (stable diffusion), so they need one more paper.
    return [a for a, n in found.most_common() if n >= (3 if len(a) <= 2 else 2)]


def _stems(tokens: list[str]) -> list[str]:
    out = []
    for t in tokens:
        if re.search(r"(x|ch|sh|ss)es$", t):
            t = t[:-2]
        elif t.endswith("s") and not t.endswith("ss") and len(t) > 3:
            t = t[:-1]
        out.append(t)
    return out


_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def phrases(query: str, texts: list[str], taken: list[str]) -> tuple[list[str], list[str]]:
    """Phrases ending in the query's last word that several papers use, split in two.

    Inflections of the query itself ("mixtures of experts" for "mixture of experts") are returned first,
    to be used as keywords; other phrases ("visual tracking" for "object tracking") are only offered.
    """
    words = _TOKEN.findall(clean_query(query).lower())
    if not words:
        return [], []
    head, query_stems = words[-1], _stems(re.split(r"-", "-".join(words)))
    counts: Counter = Counter()
    for text in texts:
        tokens = _TOKEN.findall((text or "").lower())
        seen = set()
        for i, tok in enumerate(tokens):
            if tok != head:
                continue
            for n in {2, 3, len(words)}:
                if n < 2 or i - n + 1 < 0:
                    continue
                gram = tokens[i - n + 1:i + 1]
                # The query's own words may be generic ("neural networks"); the words added to them may not.
                added = [t for t in gram[:-1] if t not in words]
                if gram[0] in _STOP or any(t in _STOP or t in GENERIC or len(t) <= 2 or t.isdigit() for t in added):
                    continue
                seen.add(" ".join(gram))
        counts.update(seen)
    inflections, offered = [], []
    for phrase, n in counts.most_common():
        if n < SUGGESTION_MIN_PAPERS or phrase in GENERIC:
            continue
        if any(relevance(phrase, None, [t]) > 0 for t in taken):  # "multi-object tracking" is already covered
            continue
        if _stems(re.split(r"[\s-]+", phrase)) == query_stems:
            inflections.append(phrase)
        else:
            offered.append(phrase)
    return inflections, offered[:MAX_SUGGESTIONS]


# ── proposal ───────────────────────────────────────────────────────────


def pick_fields(counts: list[tuple[str, int]]) -> list[str]:
    total = sum(n for _, n in counts)
    if not total:
        return list(DEFAULT_FIELDS)
    picked, covered = [], 0
    for name, n in counts[:MAX_FIELDS]:
        picked.append(name)
        covered += n
        if covered >= FIELD_COVER * total:
            break
    return picked


def _in_fields(work: Work, fields: list[str]) -> bool:
    if work.work_type in EXCLUDED_TYPES or not work.title:
        return False
    # Semantic search takes no field filter. An unknown field is kept, as in corpus._in_scope.
    return not (fields and work.field_name and work.field_name not in fields)


def group_candidates(title_hits: list[Work], semantic_hits: list[Work], query: str,
                     fields: list[str]) -> list[Candidate]:
    """In-scope works, one per paper, title matches first then semantic ones, each group most cited first."""
    title_ids = {w.openalex_id for w in title_hits}  # OpenAlex stems, so "Mixtures of Experts" is a title match
    groups: dict[str, list[Work]] = {}
    semantic_ids = {w.openalex_id for w in semantic_hits}
    for work in [*title_hits, *semantic_hits]:
        if not _in_fields(work, fields):
            continue
        key = title_key(work.title)
        if len(key) < 15:  # short titles merge only within a year, as in corpus._merge_duplicates
            key = f"{key}|{work.year}"
        members = groups.setdefault(key, [])
        if all(m.openalex_id != work.openalex_id for m in members):
            members.append(work)
    candidates = []
    for members in groups.values():
        members.sort(key=lambda w: w.cited_by_count, reverse=True)
        main = members[0]
        # A preprint and its proceedings record are a year or two apart; a generic title ("Object
        # tracking") shared by papers further apart in time is a different paper, and is left out.
        members = [main, *(w for w in members[1:] if not (w.year and main.year) or abs(w.year - main.year) <= 2)]
        candidates.append(Candidate(
            openalex_id=main.openalex_id, title=main.title, year=main.year,
            citations=max(w.cited_by_count for w in members), kind=classify_kind(main.title, main.work_type),
            venue=main.venue, alt_ids=[w.openalex_id for w in members[1:]],
            title_match=any(w.openalex_id in title_ids for w in members),
            semantic=any(w.openalex_id in semantic_ids for w in members),
            abstract=next((w.abstract for w in members if w.abstract), None)))
    titled = sorted([c for c in candidates if c.title_match], key=lambda c: -c.citations)[:TITLE_CANDIDATES]
    others = sorted([c for c in candidates if not c.title_match], key=lambda c: -c.citations)
    others = others[:TITLE_CANDIDATES + SEMANTIC_CANDIDATES - len(titled)]
    return sorted(titled + others, key=lambda c: -c.citations)


def pick_anchors(candidates: list[Candidate]) -> list[str]:
    """The most-cited method paper per third of the years, the most cited overall, and one survey."""
    pool = [c for c in candidates if c.title_match and c.year] or [c for c in candidates if c.year]
    methods = [c for c in pool if c.kind == "method"] or pool
    picked: list[str] = []
    if methods:
        years = sorted(c.year for c in methods)
        cuts = [years[len(years) // 3], years[2 * len(years) // 3]]
        thirds = [[c for c in methods if c.year < cuts[0]],
                  [c for c in methods if cuts[0] <= c.year < cuts[1]],
                  [c for c in methods if c.year >= cuts[1]]]
        for third in thirds:
            if third:
                picked.append(max(third, key=lambda c: c.citations).openalex_id)
        top = max(methods, key=lambda c: c.citations).openalex_id
        if top not in picked:
            picked.append(top)
    surveys = [c for c in pool if c.kind == "survey" and c.openalex_id not in picked]
    if surveys and len(picked) < MAX_ANCHORS:
        picked.append(max(surveys, key=lambda c: c.citations).openalex_id)
    return list(dict.fromkeys(picked))[:MAX_ANCHORS]


def propose(query: str, client: OpenAlexClient | None = None) -> dict:
    """A proposal (JSON-ready) for ``query``: three OpenAlex searches, then rules."""
    client = client or OpenAlexClient()
    query = clean_query(query)
    terms = variants(query)
    spent_before = client.spent_usd
    try:
        field_counts = client.field_counts(terms)
    except Exception:  # an unanswered grouping must not lose the proposal; Computer Science is the default
        field_counts = []
    fields = pick_fields(field_counts)
    title_hits = client.search_works(terms, TITLE_HITS, fields, in_title=True)
    semantic_hits = client.semantic_search(query)
    candidates = group_candidates(title_hits, semantic_hits, query, fields)

    # Every hit in the fields, not only the ~30 candidates, so phrases and acronyms have more papers to come from.
    hits = {w.openalex_id: w for w in [*title_hits, *semantic_hits] if _in_fields(w, fields)}
    texts = [f"{w.title}. {w.abstract or ''}" for w in hits.values()]
    acr = acronyms(query, texts)
    keywords = lint_keywords([*terms, *acr], query) or [terms[0]]
    inflections, offered = phrases(query, texts, keywords)
    keywords = lint_keywords([*keywords, *inflections], query)
    return {
        "id": uuid4().hex,
        "query": query,
        "created_at": time.time(),
        "name": topic_name(query),
        "description": "",
        "aliases": list(dict.fromkeys([*terms, *acr]))[:MAX_ALIASES],
        "fields": fields,
        "field_counts": [[name, n] for name, n in field_counts[:6]],
        "candidates": [c.public() for c in candidates],
        "anchors": pick_anchors(candidates),
        "keywords": keywords,
        "keyword_suggestions": offered,
        "cost_usd": round(client.spent_usd - spent_before, 4),
        "refine": {"status": "unavailable"},
        # Not sent to the browser: the 9B reads the start of each abstract.
        "_abstracts": {c.openalex_id: (c.abstract or "")[:300] for c in candidates},
    }


# ── the 9B ─────────────────────────────────────────────────────────────


def refine_prompt(proposal: dict) -> str:
    abstracts = proposal.get("_abstracts") or {}

    def line(i: int, c: dict) -> str:
        text = f"{i}. {c['title']} ({c['year'] or 'year unknown'}, {c['citations']} citations)"
        snippet = " ".join((abstracts.get(c["openalex_id"]) or "").split())[:200]
        return f"{text}\n   {snippet}" if snippet else text

    listed = "\n".join(line(i, c) for i, c in enumerate(proposal["candidates"], start=1))
    return (
        f"A researcher wants to see how this research topic developed: \"{proposal['query']}\".\n"
        f"Candidate papers:\n{listed}\n\n"
        "Return JSON with:\n"
        "- name: the topic's usual name, at most six words.\n"
        "- description: one plain sentence saying what the topic is about.\n"
        "- aliases: other names and abbreviations people use for the topic (at most 8).\n"
        "- keywords: words or short phrases whose presence in a paper's title shows the paper is about this "
        "topic (at most 15). Use specific terms, including the names of the topic's main methods. Avoid words "
        "used across all of machine learning, such as model, network, transformer or fine-tuning.\n"
        "- anchors: the numbers of 2 to 5 listed papers that introduced or defined the topic's main methods, "
        "spread over its history: early, middle and recent. Pick surveys only if nothing else fits, and only "
        "listed numbers."
    )


def refine_schema(n_candidates: int) -> dict:
    strings = {"type": "array", "items": {"type": "string", "maxLength": 60}}
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 60},
            "description": {"type": "string", "maxLength": 300},
            "aliases": strings | {"maxItems": MAX_ALIASES},
            "keywords": strings | {"maxItems": 15},
            "anchors": {"type": "array", "items": {"type": "integer", "enum": list(range(1, n_candidates + 1))},
                        "minItems": 1, "maxItems": MAX_ANCHORS},
        },
        "required": ["name", "description", "aliases", "keywords", "anchors"],
        "additionalProperties": False,
    }


def merge_refinement(proposal: dict, answer: dict | None) -> dict:
    """The 9B's answer checked against the proposal; anything unusable keeps the rules' value."""
    answer = answer or {}
    candidates = proposal["candidates"]
    picks = []
    for n in answer.get("anchors") or []:
        if isinstance(n, int) and 1 <= n <= len(candidates):
            picks.append(candidates[n - 1]["openalex_id"])
    picks = list(dict.fromkeys(picks))[:MAX_ANCHORS]
    if len(picks) >= 2:
        picks = _keep_spread(picks, proposal["anchors"], candidates)
    name = " ".join(str(answer.get("name") or "").split())
    description = " ".join(str(answer.get("description") or "").split())
    aliases = [" ".join(str(a).split()) for a in answer.get("aliases") or [] if str(a).strip()]
    model_keywords = lint_keywords([str(k) for k in answer.get("keywords") or []], proposal["query"])
    return {
        "name": name if 0 < len(name.split()) <= 8 else proposal["name"],
        "description": description[:300],
        "aliases": list(dict.fromkeys([*proposal["aliases"], *aliases]))[:MAX_ALIASES * 2],
        # The query's own spellings always stay; the 9B adds to them.
        "keywords": list(dict.fromkeys([*proposal["keywords"], *model_keywords]))[:MAX_KEYWORDS],
        "anchors": picks if len(picks) >= 2 else proposal["anchors"],
        "anchors_from_model": len(picks) >= 2,
    }


def _keep_spread(model: list[str], rules: list[str], candidates: list[dict]) -> list[str]:
    """The 9B's anchors, plus the rules' picks for periods it left out, farthest first.

    Asked for anchors "from different periods", the 9B still chose four object-tracking papers from
    2002-2010, so the corpus would have grown from the classic trackers only.
    """
    years = {c["openalex_id"]: c["year"] for c in candidates}
    chosen = [years[a] for a in model if years.get(a)]
    gaps = []
    for a in rules:
        if a in model or not years.get(a) or not chosen:
            continue
        distance = min(abs(years[a] - y) for y in chosen)
        if distance > ANCHOR_GAP_YEARS:
            gaps.append((distance, a))
    added = [a for _, a in sorted(gaps, reverse=True)]
    return (model + added)[:max(MAX_MERGED_ANCHORS, len(model))]


def refine(proposal: dict, classifier: "Classifier") -> dict:
    answer = classifier.ask(refine_prompt(proposal), refine_schema(len(proposal["candidates"])), "topic_proposal",
                            max_tokens=700)
    return merge_refinement(proposal, answer)


def run_refinement(proposal_id: str, r=None) -> str:
    """The Celery side: start (or reuse) the 9B, refine a pending proposal, store the answer."""
    from athena.core.redis_client import get_redis
    from athena.evolution.classify import Classifier
    from athena.evolution.gpu import chat_server  # the worker image only

    r = r or get_redis(decode_responses=True)
    proposal = load(r, proposal_id)
    if proposal is None or (proposal.get("refine") or {}).get("status") != "pending":
        return "skipped"  # built already, or gone
    proposal["refine"] = {**proposal["refine"], "status": "running", "started_at": time.time()}
    save(r, proposal)
    try:
        url, server = chat_server()
        with server:
            clf = Classifier(base_url=url)
            state = {"status": "done", "model": clf.model, **refine(proposal, clf)}
    except Exception as exc:
        state = {"status": "failed", "error": str(exc)[:300]}
    latest = load(r, proposal_id) or proposal
    if (latest.get("refine") or {}).get("status") == "running":
        latest["refine"] = state
        save(r, latest)
    return state["status"]


# ── storage ────────────────────────────────────────────────────────────


def save(r, proposal: dict) -> None:
    r.setex(REDIS_PREFIX + proposal["id"], PROPOSAL_TTL_SECONDS, json.dumps(proposal))


def load(r, proposal_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{32}", proposal_id or ""):
        return None
    raw = r.get(REDIS_PREFIX + proposal_id)
    return json.loads(raw) if raw else None


def public(proposal: dict) -> dict:
    """What the browser sees: no abstracts, and a refinement the GPU never picked up shows as expired."""
    out = {k: v for k, v in proposal.items() if not k.startswith("_")}
    refine_state = dict(out.get("refine") or {})
    if refine_state.get("status") == "pending" and time.time() > refine_state.get("deadline", 0):
        refine_state["status"] = "expired"
    out["refine"] = refine_state
    return out
