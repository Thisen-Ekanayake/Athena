"""
Citation-graph algorithms for a topic: PageRank, year-cohort percentiles,
search path count (SPC) weights and main paths.

Edges are (citing, cited). Main path analysis (Hummon & Doreian, 1989) runs
on the knowledge-flow direction, cited -> citing: an edge's SPC weight is
the number of source-to-sink paths through it, where sources are papers
citing nothing in the topic and sinks are papers nobody in the topic cites.
The global main path is the source-to-sink path with the largest total SPC;
key-route paths (Liu & Lu, 2012) extend greedily both ways from the
heaviest edges.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import igraph as ig


@dataclass
class CitationGraph:
    ids: list[str]
    index: dict[str, int]
    graph: ig.Graph                     # directed citing -> cited, acyclic
    dropped_time_reversed: int = 0      # edges where the citing paper is older than the cited one
    dropped_for_cycles: int = 0
    edges: list[tuple[str, str]] = field(default_factory=list)

    def refs(self, node: str) -> list[str]:
        """Papers ``node`` cites."""
        return [self.ids[i] for i in self.graph.successors(self.index[node])]

    def citers(self, node: str) -> list[str]:
        """Papers citing ``node``."""
        return [self.ids[i] for i in self.graph.predecessors(self.index[node])]


def build_graph(nodes: Iterable[str], edges: Iterable[tuple[str, str]],
                years: dict[str, int | None]) -> CitationGraph:
    """Build an acyclic citation graph, dropping impossible and cycle-forming edges."""
    ids = sorted(set(nodes))
    index = {n: i for i, n in enumerate(ids)}
    kept, reversed_count = [], 0
    for citing, cited in set(edges):
        if citing not in index or cited not in index or citing == cited:
            continue
        y_citing, y_cited = years.get(citing), years.get(cited)
        if y_citing is not None and y_cited is not None and y_citing < y_cited:
            reversed_count += 1
            continue
        kept.append((index[citing], index[cited]))
    g = ig.Graph(n=len(ids), edges=sorted(kept), directed=True)
    cycle_count = 0
    if not g.is_dag():
        cut = g.feedback_arc_set(None, "eades")  # positional: the keyword is algo before igraph 1.0, method after
        g.delete_edges(cut)
        cycle_count = len(cut)
    edge_list = [(ids[a], ids[b]) for a, b in g.get_edgelist()]
    return CitationGraph(ids=ids, index=index, graph=g, dropped_time_reversed=reversed_count,
                         dropped_for_cycles=cycle_count, edges=edge_list)


def pagerank(cg: CitationGraph, damping: float = 0.85) -> dict[str, float]:
    if not cg.ids:
        return {}
    scores = cg.graph.pagerank(directed=True, damping=damping)
    return dict(zip(cg.ids, scores))


def degrees(cg: CitationGraph) -> tuple[dict[str, int], dict[str, int]]:
    """(in-degree = citations from inside the topic, out-degree = references inside the topic)."""
    g = cg.graph
    return (dict(zip(cg.ids, g.indegree())), dict(zip(cg.ids, g.outdegree())))


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """Mid-rank percentile in [0, 1]: share of items below, counting ties as half."""
    ordered = sorted(values.values())
    n = len(ordered)
    out = {}
    for key, value in values.items():
        below = bisect_left(ordered, value)
        equal = bisect_right(ordered, value) - below
        out[key] = (below + 0.5 * equal) / n if n else 0.0
    return out


def log_scaled(values: dict[str, float]) -> dict[str, float]:
    """Map positive values onto [0, 1] on a log scale between the smallest positive value and the largest.

    Percentile ranks flatten the extreme tail where milestones live: they scored Faster R-CNN (579
    in-topic citations) almost the same as a paper with 69. A log scale keeps the orders of magnitude.
    """
    positive = [v for v in values.values() if v > 0]
    if not positive:
        return {k: 0.0 for k in values}
    low, high = min(positive), max(positive)
    if high == low:
        return {k: (1.0 if v > 0 else 0.0) for k, v in values.items()}
    span = math.log(high / low)
    return {k: (math.log(v / low) / span if v > 0 else 0.0) for k, v in values.items()}


def count_scaled(values: dict[str, float]) -> dict[str, float]:
    """log(1 + count) relative to the largest count, in [0, 1]."""
    top = max(values.values(), default=0)
    return {k: (math.log1p(v) / math.log1p(top) if top > 0 else 0.0) for k, v in values.items()}


def cohort_scaled(values: dict[str, float], years: dict[str, int | None], window: int = 2) -> dict[str, float]:
    """log(1 + value) relative to the largest value among papers within ``window`` years.

    Compared within a cohort so a strong recent paper is not buried under older ones that had
    more years to collect citations.
    """
    best_by_year: dict[int, float] = defaultdict(float)
    for key, value in values.items():
        if years.get(key) is not None:
            best_by_year[years[key]] = max(best_by_year[years[key]], value)
    out = {}
    for key, value in values.items():
        year = years.get(key)
        if year is None:
            out[key] = 0.0
            continue
        top = max(best_by_year.get(y, 0.0) for y in range(year - window, year + window + 1))
        out[key] = math.log1p(value) / math.log1p(top) if top > 0 else 0.0
    return out


def _path_counts(cg: CitationGraph) -> tuple[list[int], list[int], int]:
    """Knowledge-flow path counts: (paths from a source to each node, paths from each node to a sink, total)."""
    g = cg.graph
    order = g.topological_sorting(mode="out")  # citing papers before the papers they cite
    # paths_in[x]: paths from a source (a paper citing nothing here) down to x.
    paths_in = [0] * g.vcount()
    for v in reversed(order):
        refs = g.successors(v)
        paths_in[v] = 1 if not refs else sum(paths_in[r] for r in refs)
    # paths_out[x]: paths from x to a sink (a paper nothing here cites).
    paths_out = [0] * g.vcount()
    for v in order:
        citers = g.predecessors(v)
        paths_out[v] = 1 if not citers else sum(paths_out[c] for c in citers)
    total = sum(paths_out[v] for v in range(g.vcount()) if not g.successors(v)) or 1
    return paths_in, paths_out, total


def spc_weights(cg: CitationGraph) -> dict[tuple[str, str], float]:
    """Normalised search path count for each (citing, cited) edge."""
    paths_in, paths_out, total = _path_counts(cg)
    return {
        (cg.ids[citing], cg.ids[cited]): paths_in[cited] * paths_out[citing] / total
        for citing, cited in cg.graph.get_edgelist()
    }


def node_flow(cg: CitationGraph) -> dict[str, float]:
    """Share of source-to-sink paths passing through each paper: a continuous version of being on the main path."""
    if not cg.ids:
        return {}
    paths_in, paths_out, total = _path_counts(cg)
    return {cg.ids[v]: paths_in[v] * paths_out[v] / total for v in range(cg.graph.vcount())}


def global_main_path(cg: CitationGraph, weights: dict[tuple[str, str], float]) -> list[tuple[str, str]]:
    """The source-to-sink path (in knowledge-flow order) with the largest total SPC."""
    g = cg.graph
    if g.ecount() == 0:
        return []
    best = [0.0] * g.vcount()
    back: list[int | None] = [None] * g.vcount()
    for v in reversed(g.topological_sorting(mode="out")):  # oldest first
        for r in g.successors(v):  # v cites r: flow r -> v
            score = best[r] + weights[(cg.ids[v], cg.ids[r])]
            if back[v] is None or score > best[v]:
                best[v], back[v] = score, r
    sinks = [v for v in range(g.vcount()) if not g.predecessors(v) and back[v] is not None]
    if not sinks:
        return []
    node = max(sinks, key=lambda v: best[v])
    path = []
    while back[node] is not None:
        path.append((cg.ids[node], cg.ids[back[node]]))
        node = back[node]
    return list(reversed(path))


def key_route_main_paths(cg: CitationGraph, weights: dict[tuple[str, str], float],
                         routes: int = 3) -> set[tuple[str, str]]:
    """Extend greedily from each of the ``routes`` heaviest edges to a source and a sink."""
    selected: set[tuple[str, str]] = set()
    for citing, cited in sorted(weights, key=weights.get, reverse=True)[:routes]:
        selected.add((citing, cited))
        node = citing
        while True:  # forward in time: follow the heaviest citation of ``node``
            options = [(c, node) for c in cg.citers(node)]
            if not options:
                break
            edge = max(options, key=weights.get)
            selected.add(edge)
            node = edge[0]
        node = cited
        while True:  # back in time: follow the heaviest reference of ``node``
            options = [(node, r) for r in cg.refs(node)]
            if not options:
                break
            edge = max(options, key=weights.get)
            selected.add(edge)
            node = edge[1]
    return selected


def main_path(cg: CitationGraph, routes: int = 3) -> list[tuple[str, str, float]]:
    """Union of the global and key-route main paths, as (citing, cited, spc_weight)."""
    weights = spc_weights(cg)
    edges = set(global_main_path(cg, weights)) | key_route_main_paths(cg, weights, routes)
    return sorted(((c, r, weights[(c, r)]) for c, r in edges), key=lambda e: -e[2])
