"""
Build a topic's paper set from its seeds.

1. Fetch the seeds (free lookups), the papers they reference, and the most
   cited works citing each seed.
2. Accept candidates linked to at least ``min_links`` accepted papers (citing
   them or cited by them), repeating until nothing changes. A paper that cites
   only one seed can still join through other accepted papers, the way Fast
   R-CNN joins through R-CNN and SPPnet.
3. Merge duplicate OpenAlex records of the same paper (preprint vs proceedings).
4. Repair years: a paper cannot be younger than the papers citing it, and an
   arXiv ID records when it first appeared. OpenAlex dates the Transformer
   paper 2025; its 2017-2018 citers pull it back.

Fetching talks to OpenAlex; selection (``select_corpus``) is pure so it can
be tested without the network.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from loguru import logger

from athena.evolution.config import TopicConfig
from athena.evolution.openalex import OpenAlexClient, Work, arxiv_year

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
    cites = {wid: set(w.referenced_works) & ids for wid, w in pool.items()}
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
    options = [(arxiv_year(work.arxiv_id), "arxiv"), (work.year, "openalex"), (earliest_citer, "citers")]
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
    accepted = _accept(pool, seed_ids, config.min_links)
    works = {wid: pool[wid] for wid in accepted}

    canonical, merged = _merge_duplicates(works, seed_ids)
    edges = set()
    for wid, work in works.items():
        for ref in work.referenced_works:
            if ref in canonical and canonical[ref] != canonical[wid]:
                edges.add((canonical[wid], canonical[ref]))
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
    }
    return Corpus(papers=papers, edges=edges, stats=stats)


def build_corpus(client: OpenAlexClient, seeds: list[Seed], config: TopicConfig) -> Corpus:
    seed_works, candidates = fetch_candidates(client, seeds, config)
    corpus = select_corpus(seed_works, candidates, seeds, config)
    corpus.stats.update({"openalex_requests": client.requests, "openalex_spent_usd": round(client.spent_usd, 4),
                         "openalex_cache_hits": client.cache_hits})
    return corpus
