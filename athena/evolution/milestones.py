"""
Milestone scoring for a topic corpus. Deterministic: no LLM involved.

Each paper gets a weighted score from graph features (see
``MilestoneWeights``). Only on-topic method papers can be milestones:
surveys, datasets and benchmarks are scored but not picked, and neither are
papers that never mention the topic's keywords (backbones and segmentation
papers that cite DETR, say). Milestones are picked per era, with eras holding
equal numbers of papers so busy recent years are not crowded out by older,
more-cited work. The highest-scoring papers overall are always milestones, so a
crowded era (2015-2016 in object detection) does not lose one to its quota.

A person's pin or unpin always wins over the automatic pick. That is applied
when reading (``athena.database.evolution``), so rebuilds never undo it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from athena.evolution import graph as g
from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Corpus

_SURVEY = re.compile(r"\b(survey|review|overview|tutorial|primer|taxonomy)\b", re.IGNORECASE)
_DATASET = re.compile(r"\b(dataset|data set|corpus|database)\b", re.IGNORECASE)
_BENCHMARK = re.compile(r"\b(benchmark|leaderboard|challenge)\b", re.IGNORECASE)
_NAMED = re.compile(r"^\s*([^:]{1,40}?)\s*:\s+\S")
# A token that looks like a coined name: internal capital, two capitals, or a digit ("LoRA", "R-CNN", "YOLOv3").
_NAME_TOKEN = re.compile(r"[a-z][A-Z]|[A-Z].*[A-Z]|\d")


def classify_kind(title: str, work_type: str | None = None) -> str:
    if work_type == "review" or _SURVEY.search(title):
        return "survey"
    if _DATASET.search(title):
        return "dataset"
    if _BENCHMARK.search(title):
        return "benchmark"
    return "method"


def relevance(title: str, abstract: str | None, keywords: list[str]) -> float:
    """1.0 if the title mentions a topic keyword, 0.5 if only the abstract does, else 0."""
    if not keywords:
        return 1.0
    words = [k.lower() for k in keywords]
    if any(k in title.lower() for k in words):
        return 1.0
    if abstract and any(k in abstract.lower() for k in words):
        return 0.5
    return 0.0


def named_method(title: str) -> str | None:
    """'LoRA: Low-Rank Adaptation...' -> 'LoRA'. Title-only proxy; Phase 2 uses citing sentences instead."""
    match = _NAMED.match(title)
    if not match:
        return None
    name = match.group(1).strip()
    words = name.split()
    if len(words) == 1 or (len(words) <= 3 and any(_NAME_TOKEN.search(w) for w in words)):
        return name
    return None


@dataclass
class PaperScore:
    kind: str
    named_method: str | None
    in_degree: int
    out_degree: int
    pagerank: float
    citation_score: float
    specificity: float
    relevance: float
    on_main_path: bool
    milestone_score: float
    is_milestone_auto: bool = False
    detail: dict = field(default_factory=dict)


@dataclass
class TopicScores:
    papers: dict[str, PaperScore]
    main_path: list[tuple[str, str, float]]  # (citing, cited, spc_weight)
    stats: dict


def era_bounds(paper_years: list[int], eras: int, max_era_years: int) -> list[tuple[int, int]]:
    """Split years into eras holding equal numbers of papers, then cut any era longer than ``max_era_years``.

    A paper's era follows from the rank of its year, so one year never spans two eras.
    """
    ordered = sorted(paper_years)
    n = len(ordered)
    starts = sorted({ordered[min(n - 1, i * n // eras)] for i in range(eras)})
    bounds = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else ordered[-1]
        while end - start + 1 > max_era_years:
            bounds.append((start, start + max_era_years - 1))
            start += max_era_years
        bounds.append((start, end))
    return bounds


def era_of(year: int, bounds: list[tuple[int, int]]) -> tuple[int, int]:
    return next(b for b in bounds if b[0] <= year <= b[1])


def select_milestones(scores: dict[str, PaperScore], years: dict[str, int | None],
                      config: TopicConfig) -> set[str]:
    eligible = {pid: s for pid, s in scores.items()
                if s.kind == "method" and s.relevance > 0 and years.get(pid) is not None}
    if not eligible:
        return set()
    years_by_era = era_bounds([years[pid] for pid in eligible], config.eras, config.max_era_years)
    eras: dict[tuple[int, int], list[str]] = {}
    for pid in eligible:
        eras.setdefault(era_of(years[pid], years_by_era), []).append(pid)
    picked = set(sorted(eligible, key=lambda pid: eligible[pid].milestone_score, reverse=True)[:config.global_top])
    for members in eras.values():
        members.sort(key=lambda pid: eligible[pid].milestone_score, reverse=True)
        picked.update(pid for pid in members[:config.milestones_per_era]
                      if eligible[pid].milestone_score >= config.milestone_min_score)
    if config.main_path_min_score is not None:
        picked.update(pid for pid, s in eligible.items()
                      if s.on_main_path and s.milestone_score >= config.main_path_min_score)
    return picked


def score_topic(corpus: Corpus, config: TopicConfig) -> TopicScores:
    years = {pid: p.year for pid, p in corpus.papers.items()}
    cg = g.build_graph(corpus.papers, corpus.edges, years)
    in_deg, out_deg = g.degrees(cg)
    pagerank = g.pagerank(cg)
    rel = {pid: relevance(p.title, p.work.abstract, config.keywords) for pid, p in corpus.papers.items()}
    # The main path runs on the on-topic subgraph so it cannot wander through neighbouring fields.
    on_topic = {pid for pid, r in rel.items() if r > 0}
    topic_graph = g.build_graph(on_topic, [e for e in cg.edges if e[0] in on_topic and e[1] in on_topic], years)
    main = g.main_path(topic_graph, routes=config.key_routes)
    on_main = {pid for edge in main for pid in edge[:2]}
    flow = {pid: 0.0 for pid in corpus.papers} | g.node_flow(topic_graph)

    citations = {pid: float(p.work.cited_by_count) for pid, p in corpus.papers.items()}
    specificity = {pid: in_deg[pid] / max(p.work.cited_by_count, in_deg[pid], 1) for pid, p in corpus.papers.items()}
    features = {
        "citations": g.cohort_scaled(citations, years),
        "in_degree": g.count_scaled({pid: float(d) for pid, d in in_deg.items()}),
        "pagerank": g.log_scaled(pagerank),
        "flow": g.log_scaled(flow),
        "specificity": g.percentile_ranks(specificity),
    }
    w = config.weights
    scores: dict[str, PaperScore] = {}
    for pid, paper in corpus.papers.items():
        name = named_method(paper.title)
        parts = {
            "citations": w.citations * features["citations"][pid],
            "in_degree": w.in_degree * features["in_degree"][pid],
            "pagerank": w.pagerank * features["pagerank"][pid],
            "flow": w.flow * features["flow"][pid],
            "relevance": w.relevance * rel[pid],
            "specificity": w.specificity * features["specificity"][pid],
            "named_method": w.named_method * (1.0 if name else 0.0),
        }
        scores[pid] = PaperScore(
            kind=classify_kind(paper.title, paper.work.work_type),
            named_method=name,
            in_degree=in_deg[pid],
            out_degree=out_deg[pid],
            pagerank=pagerank[pid],
            citation_score=features["citations"][pid],
            specificity=specificity[pid],
            relevance=rel[pid],
            on_main_path=pid in on_main,
            milestone_score=round(sum(parts.values()), 4),
            detail={k: round(v, 4) for k, v in parts.items()},
        )
    for pid in select_milestones(scores, years, config):
        scores[pid].is_milestone_auto = True

    stats = {
        "graph_edges": cg.graph.ecount(),
        "dropped_time_reversed": cg.dropped_time_reversed,
        "dropped_for_cycles": cg.dropped_for_cycles,
        "main_path_edges": len(main),
        "on_topic_papers": len(on_topic),
        "milestones": sum(s.is_milestone_auto for s in scores.values()),
    }
    return TopicScores(papers=scores, main_path=main, stats=stats)
