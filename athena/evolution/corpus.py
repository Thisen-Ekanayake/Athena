"""
Build a topic's paper set from its seeds.

1. Fetch the seeds (free lookups), the papers they reference, and the most
   cited works citing each seed.
   Semantic Scholar then fills the reference lists OpenAlex lacks, and adds
   papers that several pool papers cite but OpenAlex never linked to the
   seeds (``augment_with_s2``).
2. Accept candidates linked to at least ``min_links`` accepted papers (citing
   them or cited by them), repeating until nothing changes. A paper that cites
   only one seed can still join through other accepted papers, the way Fast
   R-CNN joins through R-CNN and SPPnet.
3. Merge duplicate OpenAlex records of the same paper (preprint vs proceedings).
4. Repair years: a paper cannot be younger than the papers citing it, and an
   arXiv ID records when it first appeared. OpenAlex dates the Transformer
   paper 2025; its 2017-2018 citers pull it back.

Fetching talks to OpenAlex and Semantic Scholar; selection
(``select_corpus``) is pure so it can be tested without the network.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from loguru import logger

from athena.evolution.config import TopicConfig
from athena.core.openalex import OpenAlexClient, Work, arxiv_year
from athena.core.semantic_scholar import (
    CANDIDATE_FIELDS, S2Paper, S2Ref, SemanticScholarAuthError, SemanticScholarClient, lookup_id,
)

# OpenAlex work types that are never research contributions.
EXCLUDED_TYPES = {"paratext", "erratum", "retraction", "editorial", "letter", "peer-review", "supplementary-materials"}
# Year sources in order of preference when two give the same year.
_YEAR_SOURCE_ORDER = ["seed", "arxiv", "openalex", "citers"]


@dataclass
class Seed:
    openalex_id: str
    title: str | None = None   # trusted over OpenAlex's title, which can be wrong
    year: int | None = None    # trusted over OpenAlex's year
    arxiv_id: str | None = None
    # Other OpenAlex records of the same paper (e.g. the arXiv preprint next to the proceedings
    # version). Their citers are fetched too, and citations to them count as citations to the seed.
    alt_ids: list[str] = field(default_factory=list)


@dataclass
class CorpusPaper:
    work: Work
    year: int | None
    year_source: str
    role: str  # seed | core
    merged_ids: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.work.title


@dataclass
class Corpus:
    papers: dict[str, CorpusPaper]   # openalex_id -> paper
    edges: set[tuple[str, str]]      # (citing, cited) openalex ids, both in ``papers``
    stats: dict = field(default_factory=dict)
    edge_sources: dict[tuple[str, str], str] = field(default_factory=dict)  # openalex | s2; missing means openalex


_SURVEY = re.compile(r"\b(survey|review|overview|tutorial|primer|taxonomy)\b", re.IGNORECASE)
_DATASET = re.compile(r"\b(dataset|data set|corpus|database)\b", re.IGNORECASE)
_BENCHMARK = re.compile(r"\b(benchmark|leaderboard|challenge)\b", re.IGNORECASE)


def classify_kind(title: str, work_type: str | None = None) -> str:
    """method | survey | dataset | benchmark, from the title (and OpenAlex's type for reviews)."""
    if work_type == "review" or _SURVEY.search(title):
        return "survey"
    if _DATASET.search(title):
        return "dataset"
    if _BENCHMARK.search(title):
        return "benchmark"
    return "method"


def _keyword_part(keyword: str) -> str:
    k = keyword.lower()
    if len(k) > 2 and k[0] == k[-1] == '"':
        # Quoted: the whole word only (a plural too), for acronyms such as "mot" that start common words.
        return re.escape(k[1:-1]) + r"(?:e?s)?(?![a-z0-9])"
    return re.escape(k)


@lru_cache(maxsize=64)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern:
    # Keywords match at the start of a word: "lora" finds "LoRA" and "LoRAs" but not "exploration",
    # and the stem "detect" finds "detection" and "detector". A quoted keyword ('"mot"') matches the
    # whole word only, so it does not find "motion".
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(_keyword_part(k) for k in keywords) + ")")


def relevance(title: str, abstract: str | None, keywords: list[str]) -> float:
    """1.0 if the title mentions a topic keyword, 0.5 if only the abstract does, else 0."""
    if not keywords:
        return 1.0
    pattern = _keyword_pattern(tuple(keywords))
    if pattern.search(title.lower()):
        return 1.0
    if abstract and pattern.search(abstract.lower()):
        return 0.5
    return 0.0


def all_refs(work: Work) -> list[str]:
    """References from both sources."""
    return list(dict.fromkeys([*work.referenced_works, *work.s2_refs]))


# ── fetching ───────────────────────────────────────────────────────────


def fetch_candidates(client: OpenAlexClient, seeds: list[Seed],
                     config: TopicConfig) -> tuple[dict[str, Work], dict[str, Work]]:
    """Seed works, plus candidate works: the seeds' references and their top citers."""
    seed_works: dict[str, Work] = {}
    for seed in seeds:
        work = client.get_work(seed.openalex_id)
        if work is None:
            logger.warning(f"Seed {seed.openalex_id} not found in OpenAlex; skipping it")
            continue
        if work.openalex_id != seed.openalex_id:
            # OpenAlex merged the record; follow it so the seed's title and year still apply.
            logger.info(f"Seed {seed.openalex_id} now resolves to {work.openalex_id}")
            seed.openalex_id = work.openalex_id
        seed_works[work.openalex_id] = work

    references = {r for w in seed_works.values() for r in w.referenced_works} - set(seed_works)
    candidates = {w.openalex_id: w for w in client.get_works(sorted(references))}
    record_ids = list(seed_works) + [alt for s in seeds if s.openalex_id in seed_works for alt in s.alt_ids]
    for record_id in record_ids:
        for work in client.citing_works(record_id, config.citers_per_seed):
            candidates.setdefault(work.openalex_id, work)
    for seed_id in seed_works:
        candidates.pop(seed_id, None)
    logger.info(f"Fetched {len(seed_works)} seeds and {len(candidates)} candidates "
                f"({client.requests} requests, ${client.spent_usd:.4f}, {client.cache_hits} cache hits)")
    return seed_works, candidates


def add_openalex_hits(client: OpenAlexClient, seed_works: dict[str, Work], candidates: dict[str, Work],
                      search_terms: list[str], config: TopicConfig) -> dict:
    """The most-cited OpenAlex works matching the topic's name or aliases, as candidates.

    Without Semantic Scholar this is how a topic reaches papers its seeds' citer lists miss. They join
    the corpus only through ``min_links``, like every candidate.
    """
    # Short single words ("moe", "mot") mean other things in other fields; phrases are safer to search.
    terms = [t.strip('"') for t in search_terms if len(t.strip('"')) >= 5 or re.search(r"[\s-]", t)]
    if not (config.openalex_search_max and terms):
        return {}
    hits = client.search_works(terms, config.openalex_search_max, config.fields)
    added = 0
    for work in hits:
        if work.openalex_id not in seed_works and work.openalex_id not in candidates:
            candidates[work.openalex_id] = work
            added += 1
    logger.info(f"OpenAlex search: {len(hits)} hits, {added} new candidates")
    return {"openalex_search_hits": len(hits), "openalex_search_added": added}


# ── Semantic Scholar ───────────────────────────────────────────────────


def same_title(a: str, b: str) -> bool:
    """Titles of the same paper from two sources: equal word tokens, or nearly (Jaccard >= 0.8)."""
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    ta, tb = set(ka.split()), set(kb.split())
    return len(ta & tb) / len(ta | tb) >= 0.8


def _mag_id(openalex_id: str) -> str | None:
    lookup = lookup_id(openalex_id=openalex_id)
    return lookup[4:] if lookup and lookup.startswith("MAG:") else None


class _PoolIndex:
    """Finds the pool paper a Semantic Scholar record refers to, by arXiv ID, DOI, MAG ID or title."""

    def __init__(self):
        self.by_key: dict[str, str] = {}

    def add(self, wid: str, work: Work, s2: S2Ref | None = None) -> None:
        keys = [f"arxiv:{work.arxiv_id}" if work.arxiv_id else None,
                f"doi:{work.doi.lower()}" if work.doi else None,
                f"mag:{_mag_id(wid)}" if _mag_id(wid) else None,
                self._title(work.title, _first_seen(work))]
        if s2 is not None:
            keys += [f"s2:{s2.paper_id}" if s2.paper_id else None, *self._keys(s2)]
        for key in keys:
            if key:
                self.by_key.setdefault(key, wid)

    def find(self, ref: S2Ref) -> str | None:
        for key in [f"s2:{ref.paper_id}" if ref.paper_id else None, *self._keys(ref)]:
            if key and key in self.by_key:
                return self.by_key[key]
        return None

    def _keys(self, ref: S2Ref) -> list[str | None]:
        return [f"arxiv:{ref.arxiv_id}" if ref.arxiv_id else None, f"doi:{ref.doi}" if ref.doi else None,
                f"mag:{ref.mag_id}" if ref.mag_id else None, self._title(ref.title, ref.year)]

    @staticmethod
    def _title(title: str, year: int | None) -> str | None:
        key = title_key(title or "")
        if not key:
            return None
        # Short titles ("Fast R-CNN") need the year too, as in _merge_duplicates. Years differ between
        # sources by one now and then, so a short title only matches within its own year.
        return f"title:{key}" if len(key) >= 15 else (f"title:{key}|{year}" if year else None)


def _s2_lookup(wid: str, work: Work) -> str | None:
    return lookup_id(work.arxiv_id, work.doi, wid)


def _to_openalex(oa: OpenAlexClient, papers: list[S2Paper]) -> dict[str, Work]:
    """OpenAlex records for Semantic Scholar papers, by DOI (arXiv papers have one) or MAG ID, checked by title."""
    dois = {}
    mags = {}
    for p in papers:
        doi = p.doi or (f"10.48550/arxiv.{p.arxiv_id}".lower() if p.arxiv_id else None)
        if doi:
            dois[doi] = p
        elif p.mag_id:
            mags[f"W{p.mag_id}"] = p
    found: dict[str, Work] = {}
    for work in oa.get_works_by_doi(list(dois)):
        p = dois.get((work.doi or "").lower())
        if p is not None and same_title(work.title, p.title):
            found[p.paper_id] = work
    for work in oa.get_works(list(mags)):
        p = mags.get(work.openalex_id)
        if p is not None and same_title(work.title, p.title):
            found[p.paper_id] = work
    return found


def search_query(terms: list[str]) -> str:
    """A Semantic Scholar bulk-search query matching any of the terms: '"low-rank adaptation" | lora'."""
    parts = []
    for term in dict.fromkeys(t.strip().lower().replace('"', "") for t in terms if t.strip()):
        parts.append(f'"{term}"' if re.search(r"[\s-]", term) else term)
    return " | ".join(parts)


def _add_search_hits(s2: SemanticScholarClient, oa: OpenAlexClient, pool: dict[str, Work],
                     candidates: dict[str, Work], terms: list[str], config: TopicConfig) -> tuple[int, int]:
    hits = s2.search_bulk(search_query(terms), config.s2_search_max)
    known = _PoolIndex()
    for wid, work in pool.items():
        known.add(wid, work)
    new = [p for p in hits if known.find(p) is None]
    resolved = _to_openalex(oa, new)
    added = 0
    for paper in new:
        work = resolved.get(paper.paper_id)
        if work is None or work.openalex_id in pool or not _in_scope(work, config):
            continue
        work.abstract = work.abstract or paper.abstract
        candidates[work.openalex_id] = pool[work.openalex_id] = work
        added += 1
    return len(hits), added


def augment_with_s2(s2: SemanticScholarClient, oa: OpenAlexClient, seed_works: dict[str, Work],
                    candidates: dict[str, Work], seeds: list[Seed], config: TopicConfig,
                    search_terms: list[str] = ()) -> dict:
    """Add Semantic Scholar's references and citation counts to the pool, and fetch papers it cites often.

    ``search_terms`` (the topic's name and aliases) also pull in the most cited papers matching them.
    Modifies the works in place (``s2_refs``, ``s2_cited_by_count``) and adds new candidates.
    Returns counts for the build summary.
    """
    seeds_by_id = {s.openalex_id: s for s in seeds if s.openalex_id in seed_works}
    for wid, seed in seeds_by_id.items():
        # The seed's own metadata is trusted; the proceedings record often lacks the arXiv ID.
        seed_works[wid].arxiv_id = seed_works[wid].arxiv_id or seed.arxiv_id
    seed_titles = {wid: s.title for wid, s in seeds_by_id.items() if s.title}
    pool = {wid: w for wid, w in candidates.items() if _in_scope(w, config)} | seed_works
    search_hits = search_added = 0
    if search_terms and config.s2_search_max:
        search_hits, search_added = _add_search_hits(s2, oa, pool, candidates, list(search_terms), config)
    lookups = {wid: _s2_lookup(wid, w) for wid, w in pool.items()}
    found = s2.get_papers([sid for sid in lookups.values() if sid])

    index = _PoolIndex()
    matched: dict[str, S2Paper] = {}
    mismatched = 0
    for wid, work in pool.items():
        paper = found.get(lookups[wid]) if lookups[wid] else None
        if paper is None:
            index.add(wid, work)
            continue
        # A DOI can point at the wrong OpenAlex record (LoRA's arXiv DOI did), so titles must agree.
        if not same_title(seed_titles.get(wid) or work.title, paper.title):
            mismatched += 1
            index.add(wid, work)
            continue
        matched[wid] = paper
        work.s2_paper_id = paper.paper_id
        work.s2_cited_by_count = paper.citation_count
        # Proceedings records often lack the arXiv ID (ControlNet's ICCV record), which full text needs.
        work.arxiv_id = work.arxiv_id or paper.arxiv_id
        work.doi = work.doi or paper.doi
        index.add(wid, work, paper)
    for wid, seed in seeds_by_id.items():
        if seed.title:
            index.by_key.setdefault(_PoolIndex._title(seed.title, seed.year), wid)

    # Papers outside the pool that several pool papers cite: OpenAlex missed their link to the seeds.
    outside: dict[str, int] = defaultdict(int)
    for paper in matched.values():
        for ref in {r.paper_id for r in paper.references if r.paper_id and index.find(r) is None}:
            outside[ref] += 1
    wanted = sorted((pid for pid, n in outside.items() if n >= config.s2_expand_min_citers),
                    key=lambda pid: outside[pid], reverse=True)[:config.s2_expand_max]
    fetched = [p for p in s2.get_papers(wanted, CANDIDATE_FIELDS).values() if p is not None]
    # Only on-topic ones: the rest (Llama 2, Adam) would fill the corpus with context hubs.
    on_topic = [p for p in fetched if relevance(p.title, p.abstract, config.keywords) > 0]
    resolved = _to_openalex(oa, on_topic)
    added = 0
    for paper in on_topic:
        work = resolved.get(paper.paper_id)
        if work is None or work.openalex_id in pool:
            continue
        work.s2_paper_id = paper.paper_id
        work.s2_cited_by_count = paper.citation_count
        work.abstract = work.abstract or paper.abstract
        work.arxiv_id = work.arxiv_id or paper.arxiv_id
        candidates[work.openalex_id] = pool[work.openalex_id] = work
        matched[work.openalex_id] = paper
        index.add(work.openalex_id, work, paper)
        added += 1

    refs_added = 0
    for wid, paper in matched.items():
        work = pool[wid]
        known = set(work.referenced_works)
        work.s2_refs = [r for r in dict.fromkeys(index.find(ref) for ref in paper.references) if r and r != wid]
        refs_added += sum(1 for r in work.s2_refs if r not in known)

    stats = {
        "s2_search_hits": search_hits,
        "s2_search_added": search_added,
        "s2_matched": len(matched) - added,
        "s2_unmatched": len(pool) - len(matched),
        "s2_title_mismatch": mismatched,
        "s2_refs_added": refs_added,
        "s2_outside_wanted": len(wanted),
        "s2_outside_on_topic": len(on_topic),
        "s2_candidates_added": added,
    }
    logger.info(f"Semantic Scholar: {stats} ({s2.requests} requests, {s2.cache_hits} cache hits)")
    return stats


# ── selection (pure) ───────────────────────────────────────────────────


def _in_scope(work: Work, config: TopicConfig) -> bool:
    if work.work_type in EXCLUDED_TYPES or not work.title:
        return False
    # Unknown field is kept: OpenAlex leaves primary_topic empty for some older papers.
    return not (config.fields and work.field_name and work.field_name not in config.fields)


def title_key(title: str) -> str:
    """Lower-cased alphanumeric tokens, for matching titles across records."""
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def _accept(pool: dict[str, Work], accepted: set[str], min_links: int) -> set[str]:
    ids = set(pool)
    cites = {wid: set(all_refs(w)) & ids for wid, w in pool.items()}
    cited_by: dict[str, set[str]] = defaultdict(set)
    for wid, refs in cites.items():
        for ref in refs:
            cited_by[ref].add(wid)
    accepted = set(accepted)
    changed = True
    while changed:
        changed = False
        for wid in ids - accepted:
            if len(cites[wid] & accepted) + len(cited_by[wid] & accepted) >= min_links:
                accepted.add(wid)
                changed = True
    return accepted


def _merge_duplicates(works: dict[str, Work], seed_ids: set[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Group records with the same normalised title; map each to a canonical id (a seed, else the most cited)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for wid, work in works.items():
        key = title_key(work.title)
        # Short titles ("Fast R-CNN") only merge within the same year, so generic ones do not collide.
        groups[key if len(key) >= 15 else f"{key}|{_first_seen(work)}"].append(wid)
    canonical: dict[str, str] = {}
    merged: dict[str, list[str]] = {}
    for members in groups.values():
        keep = max(members, key=lambda m: (m in seed_ids, works[m].cited_by_count))
        for m in members:
            canonical[m] = keep
        if len(members) > 1:
            merged[keep] = [m for m in members if m != keep]
    return canonical, merged


def _repair_year(work: Work, seed: Seed | None, earliest_citer: int | None) -> tuple[int | None, str]:
    if seed and seed.year:
        return seed.year, "seed"
    options = [(arxiv_year(work.arxiv_id), "arxiv"), (work.year, "openalex")]
    # An arXiv ID records first appearance exactly, so citers only date papers without one. Semantic
    # Scholar reads references from a preprint's latest version, so a 2023 paper revised in 2024 "cites"
    # DoRA (2024) and would otherwise pull it back to 2023.
    if not work.arxiv_id:
        options.append((earliest_citer, "citers"))
    options = [(y, src) for y, src in options if y]
    if not options:
        return None, "unknown"
    return min(options, key=lambda o: (o[0], _YEAR_SOURCE_ORDER.index(o[1])))


def _citer_bound(years: list[int]) -> int | None:
    """A robust "cited by then" year: the 5th-percentile citer year, needing two or more citers.

    The single earliest citer is not enough: one citer with a wrong early date dated Faster R-CNN 2012.
    """
    if len(years) < 2:
        return None
    ordered = sorted(years)
    return ordered[max(1, math.ceil(0.05 * len(ordered))) - 1]


def _first_seen(work: Work) -> int | None:
    years = [y for y in (work.year, arxiv_year(work.arxiv_id)) if y]
    return min(years) if years else None


def select_corpus(seed_works: dict[str, Work], candidates: dict[str, Work], seeds: list[Seed],
                  config: TopicConfig) -> Corpus:
    seed_ids = set(seed_works)
    alias = {alt: s.openalex_id for s in seeds if s.openalex_id in seed_ids for alt in s.alt_ids}
    pool = {wid: w for wid, w in candidates.items() if _in_scope(w, config) and wid not in alias}
    pool.update(seed_works)
    for work in pool.values():
        work.referenced_works = list(dict.fromkeys(alias.get(r, r) for r in work.referenced_works))
        work.s2_refs = list(dict.fromkeys(alias.get(r, r) for r in work.s2_refs))
    accepted = _accept(pool, seed_ids, config.min_links)
    works = {wid: pool[wid] for wid in accepted}

    canonical, merged = _merge_duplicates(works, seed_ids)
    edges = set()
    from_openalex = set()
    for wid, work in works.items():
        oa_refs = set(work.referenced_works)
        for ref in all_refs(work):
            if ref in canonical and canonical[ref] != canonical[wid]:
                edge = (canonical[wid], canonical[ref])
                edges.add(edge)
                if ref in oa_refs:
                    from_openalex.add(edge)
    keep = set(canonical.values())

    if len(keep) > config.max_papers:
        degree: dict[str, int] = defaultdict(int)
        for citing, cited in edges:
            degree[citing] += 1
            degree[cited] += 1
        ranked = sorted(keep - seed_ids, key=lambda w: degree[w], reverse=True)
        keep = seed_ids | set(ranked[:config.max_papers - len(seed_ids & keep)])
        edges = {(a, b) for a, b in edges if a in keep and b in keep}

    citer_years: dict[str, list[int]] = defaultdict(list)
    for citing, cited in edges:
        year = _first_seen(works[citing])
        if year:
            citer_years[cited].append(year)
    earliest_citer = {}
    for pid, years in citer_years.items():
        bound = _citer_bound(years)
        if bound:
            earliest_citer[pid] = bound

    seeds_by_id = {s.openalex_id: s for s in seeds}
    papers: dict[str, CorpusPaper] = {}
    for wid in keep:
        work = works[wid]
        # The proceedings record often lacks the arXiv link its merged preprint record has.
        for member in (works[m] for m in merged.get(wid, [])):
            work.arxiv_id = work.arxiv_id or member.arxiv_id
            work.oa_pdf_url = work.oa_pdf_url or member.oa_pdf_url
            work.is_oa = work.is_oa or member.is_oa
            work.abstract = work.abstract or member.abstract
            work.s2_paper_id = work.s2_paper_id or member.s2_paper_id
            work.s2_cited_by_count = max(work.s2_cited_by_count or 0, member.s2_cited_by_count or 0) or None
        seed = seeds_by_id.get(wid)
        if seed and seed.title:
            work.title = seed.title
        if seed and seed.arxiv_id and not work.arxiv_id:
            work.arxiv_id = seed.arxiv_id
        year, source = _repair_year(work, seed, earliest_citer.get(wid))
        if wid not in seed_ids and year is not None and (
                (config.year_min and year < config.year_min) or (config.year_max and year > config.year_max)):
            continue
        papers[wid] = CorpusPaper(work=work, year=year, year_source=source,
                                  role="seed" if wid in seed_ids else "core", merged_ids=merged.get(wid, []))
    edges = {(a, b) for a, b in edges if a in papers and b in papers}

    stats = {
        "candidates": len(candidates),
        "in_scope": len(pool) - len(seed_works),
        "accepted": len(accepted),
        "duplicates_merged": sum(len(m) for m in merged.values()),
        "papers": len(papers),
        "edges": len(edges),
        "years_repaired": sum(1 for p in papers.values() if p.year_source in ("arxiv", "citers")
                              and p.year != p.work.year),
        "edges_from_s2_only": sum(1 for e in edges if e not in from_openalex),
    }
    return Corpus(papers=papers, edges=edges, stats=stats,
                  edge_sources={e: "s2" for e in edges if e not in from_openalex})


def build_corpus(client: OpenAlexClient, seeds: list[Seed], config: TopicConfig,
                 s2: SemanticScholarClient | None = None, search_terms: list[str] = (),
                 on_stage: Callable[[str], None] | None = None) -> Corpus:
    stage = on_stage or (lambda _: None)
    stage("Collecting the anchors' references and citing papers from OpenAlex")
    seed_works, candidates = fetch_candidates(client, seeds, config)
    oa_stats = add_openalex_hits(client, seed_works, candidates, list(search_terms), config)
    s2_stats: dict = {"s2": "off"}
    if config.s2:
        stage("Adding references from Semantic Scholar")
        try:
            s2 = s2 or SemanticScholarClient(keyless_ok=config.s2_keyless)
            s2_stats = augment_with_s2(s2, client, seed_works, candidates, seeds, config, search_terms)
            s2_stats |= {"s2": "used", "s2_requests": s2.requests, "s2_cache_hits": s2.cache_hits}
        except SemanticScholarAuthError as exc:
            # Only without keyless use: the build goes on with OpenAlex alone, and a rebuild adds it later.
            logger.warning(f"Skipping Semantic Scholar: {exc}")
            s2_stats = {"s2": f"skipped ({exc})"}
    stage("Selecting the papers linked to the anchors")
    corpus = select_corpus(seed_works, candidates, seeds, config)
    corpus.stats.update({"openalex_requests": client.requests, "openalex_spent_usd": round(client.spent_usd, 4),
                         "openalex_cache_hits": client.cache_hits} | oa_stats | s2_stats)
    return corpus
