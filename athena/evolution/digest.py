"""
A research map as a small graph for a chat model: its milestones and main-path papers as short ids, the main
path as chains, typed links between papers (fixes / criticises / builds on / compares) from citing sentences, the
eras, and the open problems with the papers that raised and addressed them.

It is built from the map's data, never written by a model, so it says only what the map says, costs no model time
and follows every rebuild. Text for language models reads best as named nodes and labelled edges (Fatemi et al.,
"Talk like a Graph", ICLR 2024); JSON spends tokens on syntax and Mermaid's arrows get read backwards.

Paper ids are the map's letter in the chat and a number given oldest first over the full set (A1, A2…), so the
same paper keeps its id at every level of detail. Three levels: full, compact (milestones only, no quotes) and
minimal (milestone names and the main path); the chat picks the largest that fits (athena.projects.chat).

    Map A: Parameter-efficient fine-tuning [slug peft]: 142 papers, 2017–2026
    Eras: 2017–2019 A1–A4 · 2020–2022 A5–A9
    Papers (* milestone):
    A1 2019 Adapters: Parameter-Efficient Transfer Learning for NLP *
    Main path (→ the later paper builds on the earlier): A1 → A3 → A6
    Links:
    A3 fixes A1: “adapters add inference latency”
    Open problems:
    - forgetting under sequential PEFT (persisting, 2019–2025): raised by A4, A7; addressed by A9
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

FULL, COMPACT, MINIMAL = "full", "compact", "minimal"
LEVELS = (FULL, COMPACT, MINIMAL)
MAX_NODES = 40            # milestones first, then main-path papers by milestone score
LINKS_PER_PAPER = {FULL: 3, COMPACT: 2}
GAPS = {FULL: 6, COMPACT: 3}
QUOTE_CHARS = 110
TITLE_CHARS = {FULL: 90, COMPACT: 60, MINIMAL: 40}
CACHE_SECONDS = 7 * 24 * 3600

# The citing sentence's label, strongest first, and how a link says it.
RELATIONS = {"addresses_limitation": "fixes", "criticises": "criticises", "extends_or_uses": "builds on",
             "compares": "compares with"}
RANK = {"fixes": 0, "criticises": 1, "builds on": 2, "compares with": 3, "cites": 4}
REF = re.compile(r"\b([A-Z])(\d{1,3})\b")

LEGEND = (
    "Research maps the user gave you, as graphs. Each paper has an id: the map's letter and a number, oldest "
    "first (A3). In a main path, → means the later paper builds on the earlier one along the field's main line. "
    "To mention one of these papers, write its id in square brackets, like [A3], in place of its title: the page "
    "shows the title, authors and year there and opens the paper in the map, so do not repeat them. The graph "
    "shows how the field developed; for what a paper says, call query_map and cite the passages as [n].")


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def digest(session: Session, topic) -> dict | None:
    """The map's graph data (cached per build), or None for a map that is not built."""
    if topic.built_at is None:
        return None
    key = f"athena:digest:v2:{topic.id}:{int(topic.built_at.timestamp())}"
    try:
        cached = _redis().get(key)
        if cached:
            return json.loads(cached)
    except Exception as exc:  # no Redis: build it each time
        logger.debug(f"Map digest cache unavailable: {exc}")
    data = build(session, topic)
    try:
        _redis().set(key, json.dumps(data), ex=CACHE_SECONDS)
    except Exception:
        pass
    return data


def build(session: Session, topic) -> dict:
    from athena.core.models import EvoCitation, EvoCitationContext, EvoMainPathEdge
    from athena.database.evolution.gaps import topic_gaps
    from athena.database.evolution.topics import (
        LIMITATION_LABELS, _overrides, _topic_rows, effective_milestone, method_names, topic_eras,
    )

    rows = _topic_rows(session, topic.id)
    overrides = _overrides(session, topic.id)

    def is_milestone(tp) -> bool:
        return effective_milestone(tp.is_milestone_auto, overrides[tp.paper_id].action
                                   if tp.paper_id in overrides else None)

    picked = [(tp, p) for tp, p in rows if is_milestone(tp) or tp.on_main_path]
    picked.sort(key=lambda r: (not is_milestone(r[0]), -(r[0].milestone_score or 0)))
    picked = picked[:MAX_NODES]
    picked.sort(key=lambda r: (r[1].year or 9999, -(r[0].milestone_score or 0)))
    names = method_names(session, {p.id: p.title for _, p in picked})
    number = {p.id: n for n, (_, p) in enumerate(picked, 1)}
    nodes = [{"n": number[p.id], "paper_id": str(p.id), "year": p.year, "title": p.title,
              "label": names.get(p.id) or tp.named_method, "authors": short_authors(p.authors),
              "milestone": is_milestone(tp), "main": tp.on_main_path}
             for tp, p in picked]

    ids = list(number)
    main = {(number[c], number[d]) for c, d in session.execute(
        select(EvoMainPathEdge.citing_id, EvoMainPathEdge.cited_id).where(
            EvoMainPathEdge.topic_id == topic.id, EvoMainPathEdge.citing_id.in_(ids),
            EvoMainPathEdge.cited_id.in_(ids))).all()} if ids else set()
    cites = {(number[c], number[d]) for c, d in session.execute(
        select(EvoCitation.citing_id, EvoCitation.cited_id).where(
            EvoCitation.citing_id.in_(ids), EvoCitation.cited_id.in_(ids))).all()} if ids else set()

    # The strongest labelled sentence for each pair; limitation labels only when attributed to the cited paper.
    best: dict[tuple[int, int], tuple[str, str | None]] = {}
    contexts = session.execute(select(EvoCitationContext).where(
        EvoCitationContext.citing_id.in_(ids), EvoCitationContext.cited_id.in_(ids),
        EvoCitationContext.label.in_(list(RELATIONS)))).scalars() if ids else []
    for ctx in contexts:
        if ctx.label in LIMITATION_LABELS and ctx.attributed is not True:
            continue
        pair, rel = (number[ctx.citing_id], number[ctx.cited_id]), RELATIONS[ctx.label]
        quote = _quote(ctx.sentence) if ctx.label in LIMITATION_LABELS else None
        held = best.get(pair)
        if held is None or RANK[rel] < RANK[held[0]] or (
                RANK[rel] == RANK[held[0]] and quote and (not held[1] or len(quote) < len(held[1]))):
            best[pair] = (rel, quote)
    links = [{"from": a, "to": b, "rel": rel} | ({"quote": quote} if quote else {})
             for (a, b), (rel, quote) in best.items()]
    on_path = {n for edge in main for n in edge}
    for a, b in cites:  # papers off the main path still show where they come from
        if (a, b) not in best and a not in on_path:
            links.append({"from": a, "to": b, "rel": "cites"})

    eras = [list(b) for b in topic_eras(topic, rows)]
    gaps = []
    try:
        for t in topic_gaps(session, topic, examples=0).get("themes", []):
            if t["status"] == "quiet":
                continue
            raised = [number[_uuid(p["id"])] for p in t.get("papers", []) if _uuid(p["id"]) in number]
            fixed = [number[_uuid(p["id"])] for p in t.get("fixed_by", []) if _uuid(p["id"]) in number]
            gaps.append({"label": t["label"], "status": t["status"], "years": [t.get("first_year"), t.get("last_year")],
                         "raised": sorted(set(raised))[:4], "fixed": sorted(set(fixed))[:3]})
            if len(gaps) >= GAPS[FULL]:
                break
    except Exception as exc:
        logger.warning(f"Map digest {topic.slug}: no open problems: {exc}")
    years = [p.year for _, p in rows if p.year]
    return {"slug": topic.slug, "name": topic.name, "description": (topic.description or "")[:200],
            "papers": len(rows), "years": [min(years), max(years)] if years else None, "nodes": nodes,
            "main": sorted([a, b] for a, b in main), "links": links, "eras": eras, "gaps": gaps}


def short_authors(authors) -> str | None:
    """"Hu", "Hu and Shen", or "Hu et al.": surnames, for a citation."""
    names = [a.get("name") if isinstance(a, dict) else str(a) for a in authors or []]
    surnames = [n.split()[-1] for n in names if n and n.split()]
    if not surnames:
        return None
    if len(surnames) == 1:
        return surnames[0]
    return f"{surnames[0]} and {surnames[1]}" if len(surnames) == 2 else f"{surnames[0]} et al."


def _uuid(value):
    from uuid import UUID
    return UUID(str(value))


def _quote(sentence: str | None) -> str | None:
    text = " ".join((sentence or "").split())
    if not text:
        return None
    text = re.sub(r"\s*\[\[|\]\]\s*", " ", text).strip()
    return text if len(text) <= QUOTE_CHARS else text[:QUOTE_CHARS - 1].rstrip() + "…"


def chains(edges: list[tuple[int, int]], shown: set[int]) -> list[list[int]]:
    """The main path as chains oldest first, each edge once; hidden papers are skipped over, so a chain still
    reads as ancestry (A1 → A5 when A3 is left out)."""
    forward = defaultdict(set)  # earlier -> later
    for citing, cited in edges:
        forward[cited].add(citing)

    def reach(n: int, seen: set[int]) -> set[int]:  # the nearest shown papers after n
        out = set()
        for m in forward.get(n, ()):
            if m in seen:
                continue
            seen.add(m)
            out |= {m} if m in shown else reach(m, seen)
        return out

    nxt = {n: sorted(reach(n, set())) for n in shown}
    left = {(a, b) for a, bs in nxt.items() for b in bs}
    out = []
    while left:
        a, b = min(left)
        chain = [a, b]
        left.discard((a, b))
        while True:
            step = next((c for c in nxt.get(chain[-1], []) if (chain[-1], c) in left), None)
            if step is None:
                break
            left.discard((chain[-1], step))
            chain.append(step)
        out.append(chain)
    return out


def render(data: dict, key: str, level: str = FULL) -> str:
    """The graph as text at one level of detail."""
    def pid(n: int) -> str:
        return f"{key}{n}"

    nodes = [n for n in data["nodes"] if level == FULL or n["milestone"]] or data["nodes"]
    shown = {n["n"] for n in nodes}
    years = data.get("years")
    head = f"Map {key}: {data['name']} [slug {data['slug']}]: {data['papers']} papers" + (
        f", {years[0]}–{years[1]}" if years else "")
    lines = [head]
    if level == FULL and data.get("description"):
        lines.append(data["description"])
    if level != MINIMAL:
        eras = []
        for start, end in data.get("eras") or []:
            inside = [n["n"] for n in nodes if n["year"] and start <= n["year"] <= end]
            if inside:
                span = pid(inside[0]) if len(inside) == 1 else f"{pid(inside[0])}–{pid(inside[-1])}"
                eras.append(f"{start}–{end} {span}" if start != end else f"{start} {span}")
        if eras:
            lines.append("Eras: " + " · ".join(eras))
    lines.append("Papers (* milestone):" if level == FULL else "Milestones:")
    for n in nodes:
        lines.append(f"{pid(n['n'])} {n['year'] or 'n.d.'} {_name(n, level)}"
                     + (" *" if level == FULL and n["milestone"] else ""))
    path = chains([tuple(e) for e in data.get("main") or []], shown)
    if path:
        lines.append("Main path (→ the later paper builds on the earlier): "
                     + "; ".join(" → ".join(pid(n) for n in c) for c in path))
    if level != MINIMAL:
        per: dict[int, list[dict]] = defaultdict(list)
        for link in data.get("links") or []:
            if link["from"] in shown and link["to"] in shown and (level == FULL or link["rel"] != "cites"):
                per[link["from"]].append(link)
        out = []
        for source in sorted(per):
            picks = sorted(per[source], key=lambda x: (RANK[x["rel"]], -x["to"]))[:LINKS_PER_PAPER[level]]
            for link in picks:
                quote = f": “{link['quote']}”" if level == FULL and link.get("quote") else ""
                out.append(f"{pid(source)} {link['rel']} {pid(link['to'])}{quote}")
        if out:
            lines.append("Links:\n" + "\n".join(out))
        gaps = []
        for g in (data.get("gaps") or [])[:GAPS[level]]:
            raised = [pid(n) for n in g["raised"] if n in shown]
            fixed = [pid(n) for n in g["fixed"] if n in shown]
            first, last = g["years"]
            when = f", {first}–{last}" if first and last and first != last else (f", {first}" if first else "")
            refs = "; ".join(p for p in (f"raised by {', '.join(raised)}" if raised else "",
                                         f"addressed by {', '.join(fixed)}" if fixed else "") if p)
            gaps.append(f"- {g['label']} ({g['status']}{when})" + (f": {refs}" if refs else ""))
        if gaps:
            lines.append("Open problems:\n" + "\n".join(gaps))
    return "\n".join(lines)


def _name(n: dict, level: str) -> str:
    title, label = " ".join((n["title"] or "").split()), n.get("label")
    limit = TITLE_CHARS[level]
    if level == MINIMAL:
        name = label or title
        return name if len(name) <= limit else name[:limit - 1].rstrip() + "…"
    short = title if len(title) <= limit else title[:limit - 1].rstrip() + "…"
    if label and not title.lower().startswith(label.lower()):
        return f"{label}: {short}"
    return short


def refs(data: dict, key: str) -> dict[str, dict]:
    """Every paper id in the graph, for showing an answer's mentions as citations that open the map."""
    return {f"{key}{n['n']}": {"slug": data["slug"], "map": data["name"], "paper_id": n["paper_id"],
                               "label": n.get("label") or n["title"], "title": n["title"],
                               "authors": n.get("authors"), "year": n["year"]} for n in data["nodes"]}


def mentioned(text: str, known: dict[str, dict]) -> dict[str, dict]:
    """The ids from ``known`` that ``text`` names."""
    return {m.group(0): known[m.group(0)] for m in REF.finditer(text or "") if m.group(0) in known}
