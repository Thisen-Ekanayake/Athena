"""
A map's graph: papers and citation edges, the timeline, one paper's detail, links to other maps, rising papers
and the paper export.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.core.models import (
    EvoChunk, EvoCitation, EvoCitationContext, EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink,
    EvoMainPathEdge, EvoMilestoneOverride, EvoPaper, EvoTopic, EvoTopicPaper,
)
from athena.evolution.config import TopicConfig
from athena.evolution.eras import on_topic_method
from athena.database.evolution.topics import (
    LIMITATION_LABELS, LOOSE_MIN_SCORE, _overrides, _topic_rows, effective_milestone, method_names, topic_summary,
)


def _node(tp: EvoTopicPaper, p: EvoPaper, override: EvoMilestoneOverride | None,
          method_name: str | None = None) -> dict:
    action = override.action if override else None
    return {
        "id": str(p.id),
        "openalex_id": p.openalex_id,
        "title": p.title,
        "year": p.year,
        "year_source": p.year_source,
        "authors": (p.authors or [])[:3],
        "venue": p.venue,
        "cited_by_count": max(p.cited_by_count or 0, p.s2_cited_by_count or 0),
        "kind": tp.kind,
        "role": tp.role,
        # What citing sentences call it ("LoRA [28]"), else the "Name: description" title prefix.
        "named_method": method_name or tp.named_method,
        "in_degree": tp.in_degree,
        "pagerank": tp.pagerank,
        "citation_percentile": tp.citation_percentile,
        "specificity": tp.specificity,
        "on_main_path": tp.on_main_path,
        "milestone_score": tp.milestone_score,
        "score_detail": tp.score_detail or {},
        "is_milestone": effective_milestone(tp.is_milestone_auto, action),
        "is_milestone_auto": tp.is_milestone_auto,
        "milestone_override": action,
        "override_note": override.note if override else None,
        "full_text_status": p.full_text_status,
        "url": _paper_url(p),
    }


def _strict(session: Session, citing: list[UUID] | None = None, cited: list[UUID] | None = None,
            within: set[UUID] | None = None) -> list[EvoCitationContext]:
    query = select(EvoCitationContext).where(EvoCitationContext.label.in_(LIMITATION_LABELS),
                                             EvoCitationContext.attributed.is_(True))
    if citing is not None:
        query = query.where(EvoCitationContext.citing_id.in_(citing))
    if cited is not None:
        query = query.where(EvoCitationContext.cited_id.in_(cited))
    rows = list(session.execute(query).scalars())
    if within is not None:
        rows = [r for r in rows if r.citing_id in within and r.cited_id in within]
    return rows


def _evidence(ctx: EvoCitationContext) -> dict:
    return {"sentence": ctx.sentence, "section_type": ctx.section_type, "label": ctx.label, "source": ctx.source}


def topic_graph(session: Session, topic: EvoTopic, limit: int = 250) -> dict:
    """Milestones, main-path papers and seeds, then the highest-scoring papers up to ``limit`` (0: every paper)."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    names = method_names(session, {p.id: p.title for _, p in rows})
    nodes = [_node(tp, p, overrides.get(p.id), names.get(p.id)) for tp, p in rows]
    total = len(nodes)
    nodes.sort(key=lambda n: (n["is_milestone"] or n["on_main_path"] or n["role"] == "seed",
                              n["milestone_score"]), reverse=True)
    if limit > 0:
        nodes = nodes[:max(limit, sum(1 for n in nodes if n["is_milestone"] or n["on_main_path"]))]
    shown = {UUID(n["id"]) for n in nodes}

    main = {(r.citing_id, r.cited_id) for r in session.execute(
        select(EvoMainPathEdge).where(EvoMainPathEdge.topic_id == topic.id)).scalars()}
    strict = defaultdict(list)
    for ctx in _strict(session, citing=list(shown), within=shown):
        strict[(ctx.citing_id, ctx.cited_id)].append(ctx)
    edges = [
        {"source": str(c), "target": str(d), "main_path": (c, d) in main, "strict": (c, d) in strict,
         "fixes": any(x.label == "addresses_limitation" for x in strict.get((c, d), []))}
        for c, d in session.execute(
            select(EvoCitation.citing_id, EvoCitation.cited_id)
            .where(EvoCitation.citing_id.in_(shown), EvoCitation.cited_id.in_(shown))
        ).all()
    ]
    loose: dict[tuple[UUID, UUID], float] = {}
    kinds = {tp.paper_id: tp.kind for tp, _ in rows}
    for gap_paper, later, score in session.execute(
            select(EvoGapStatement.paper_id, EvoLooseLink.paper_id, EvoLooseLink.score)
            .join(EvoGapStatement, EvoLooseLink.gap_id == EvoGapStatement.id)
            .where(EvoGapStatement.paper_id.in_(shown), EvoLooseLink.paper_id.in_(shown),
                   EvoLooseLink.score >= LOOSE_MIN_SCORE)):
        if kinds.get(later) == "method":  # a survey or dataset paper addresses nothing
            loose[(later, gap_paper)] = max(score, loose.get((later, gap_paper), 0.0))
    years = [n["year"] for n in nodes if n["year"]]
    return {
        "topic": topic_summary(topic),
        "nodes": nodes,
        "edges": edges,
        # Later paper -> earlier paper whose stated gap its text matches; no citation needed. Drawn dashed.
        "loose_edges": [{"source": str(a), "target": str(b), "score": round(v, 3)} for (a, b), v in loose.items()],
        "total_papers": total,
        "strict_links": len(strict),
        "year_range": [min(years), max(years)] if years else None,
    }


def topic_timeline(session: Session, topic: EvoTopic, notable: int = 40) -> dict:
    """Milestones by year, plus notable papers whose full text is not openly available."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    names = method_names(session, {p.id: p.title for _, p in rows})
    nodes = [_node(tp, p, overrides.get(p.id), names.get(p.id)) for tp, p in rows]
    by_year: dict[int, list[dict]] = {}
    for n in nodes:
        if n["is_milestone"] and n["year"]:
            by_year.setdefault(n["year"], []).append(n)
    top = sorted((n for n in nodes if n["kind"] == "method"), key=lambda n: n["milestone_score"], reverse=True)
    notable_ids = {n["id"] for n in top[:notable]} | {n["id"] for n in nodes if n["is_milestone"]}
    without_full_text = sorted(
        (n for n in nodes if n["id"] in notable_ids and n["full_text_status"] == "unavailable"),
        key=lambda n: n["milestone_score"], reverse=True,
    )
    return {
        "topic": topic_summary(topic),
        "years": [{"year": y, "papers": sorted(ps, key=lambda n: -n["milestone_score"])}
                  for y, ps in sorted(by_year.items())],
        "without_full_text": without_full_text,
    }


def topic_links(session: Session, topic: EvoTopic, limit: int = 40) -> dict:
    """How this map connects to the others: papers they share, and milestones one borrows from the other."""
    overrides = _overrides(session, topic.id)
    rows = {p.id: (tp, p) for tp, p in _topic_rows(session, topic.id)}
    weight = TopicConfig.from_dict(topic.config).weights.relevance
    on_topic = {pid for pid, (tp, _) in rows.items() if on_topic_method(tp.kind, tp.score_detail, weight)}
    here_milestone = {pid for pid, (tp, _) in rows.items()
                      if effective_milestone(tp.is_milestone_auto, overrides[pid].action if pid in overrides else None)}
    topics = {t.id: t for t in session.execute(
        select(EvoTopic).where(EvoTopic.id != topic.id, EvoTopic.built_at.isnot(None))).scalars()}
    pins = {(o.topic_id, o.paper_id): o.action for o in session.execute(select(EvoMilestoneOverride).where(
        EvoMilestoneOverride.topic_id.in_(list(topics)))).scalars()}
    elsewhere: dict[UUID, list[dict]] = defaultdict(list)  # paper -> its places in other maps
    milestones_elsewhere: dict[UUID, dict] = {}            # other maps' milestones, any paper
    for tp in session.execute(select(EvoTopicPaper).where(EvoTopicPaper.topic_id.in_(list(topics)))).scalars():
        is_ms = effective_milestone(tp.is_milestone_auto, pins.get((tp.topic_id, tp.paper_id)))
        if tp.paper_id in rows:
            elsewhere[tp.paper_id].append({"topic": topics[tp.topic_id].slug, "topic_name": topics[tp.topic_id].name,
                                           "milestone": is_ms})
        if is_ms:
            milestones_elsewhere.setdefault(tp.paper_id, {"topic": topics[tp.topic_id].slug,
                                                          "topic_name": topics[tp.topic_id].name})
    names = method_names(session, {pid: rows[pid][1].title for pid in elsewhere})

    def mini(pid: UUID, title: str | None = None, year: int | None = None, name: str | None = None) -> dict:
        if pid in rows:
            tp, p = rows[pid]
            return {"id": str(pid), "title": p.title, "year": p.year, "named_method": names.get(pid) or tp.named_method,
                    "is_milestone": pid in here_milestone}
        return {"id": str(pid), "title": title, "year": year, "named_method": name, "is_milestone": False}

    def shared_rank(pid: UUID) -> tuple:
        return (pid in here_milestone or any(e["milestone"] for e in elsewhere[pid]), rows[pid][0].milestone_score or 0)

    shared = sorted(elsewhere, key=shared_rank, reverse=True)

    def counted(citing_side: set[UUID], cited_side: dict[UUID, dict], exclude: set[UUID]) -> list[tuple[UUID, int]]:
        counts: dict[UUID, int] = defaultdict(int)
        if not citing_side or not cited_side:
            return []
        for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
                EvoCitation.citing_id.in_(list(citing_side)), EvoCitation.cited_id.in_(list(cited_side)))):
            if cited not in exclude:
                counts[cited] += 1
        return sorted(counts.items(), key=lambda kv: -kv[1])[:15]

    borrowed_ids = counted(on_topic, milestones_elsewhere, set(rows))
    other_papers = {pid for pid in session.execute(select(EvoTopicPaper.paper_id).where(
        EvoTopicPaper.topic_id.in_(list(topics)))).scalars()} - set(rows)
    lent_ids = counted(other_papers, {pid: {} for pid in here_milestone}, set())
    lent_by: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if lent_ids:
        topic_of = defaultdict(set)
        for pid, tid in session.execute(select(EvoTopicPaper.paper_id, EvoTopicPaper.topic_id).where(
                EvoTopicPaper.topic_id.in_(list(topics)), EvoTopicPaper.paper_id.in_(list(other_papers)))):
            topic_of[pid].add(tid)
        for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
                EvoCitation.citing_id.in_(list(other_papers)), EvoCitation.cited_id.in_([p for p, _ in lent_ids]))):
            for tid in topic_of[citing]:
                lent_by[cited][topics[tid].name] += 1
    info = {p.id: p for p in session.execute(select(EvoPaper).where(
        EvoPaper.id.in_([pid for pid, _ in borrowed_ids]))).scalars()} if borrowed_ids else {}

    def name_of(p: EvoPaper) -> str | None:
        return (p.cited_name or {}).get("name") if isinstance(p.cited_name, dict) else None

    return {
        "topic": topic_summary(topic),
        "shared": {"total": len(shared),
                   "papers": [mini(pid) | {"elsewhere": elsewhere[pid]} for pid in shared[:limit]]},
        "borrowed": [mini(pid, info[pid].title, info[pid].year, name_of(info[pid]))
                     | {"from": milestones_elsewhere[pid], "citing_papers": n}
                     for pid, n in borrowed_ids if pid in info],
        "lent": [mini(pid) | {"citing_papers": n, "by": dict(sorted(lent_by[pid].items(), key=lambda kv: -kv[1]))}
                 for pid, n in lent_ids],
    }


def _paper_url(p: EvoPaper) -> str:
    if p.arxiv_id:
        return f"https://arxiv.org/abs/{p.arxiv_id}"
    return f"https://doi.org/{p.doi}" if p.doi else f"https://openalex.org/{p.openalex_id}"


def export_papers(session: Session, paper_ids: list[UUID]) -> list[dict]:
    """Citation data for papers, in the order given, with every stored author."""
    rows = {p.id: p for p in session.execute(select(EvoPaper).where(EvoPaper.id.in_(paper_ids))).scalars()}
    return [{"id": str(p.id), "title": p.title, "year": p.year, "authors": [a for a in p.authors or [] if a],
             "venue": p.venue, "doi": p.doi, "arxiv_id": p.arxiv_id, "url": _paper_url(p)}
            for p in (rows.get(i) for i in paper_ids) if p is not None]


def paper_detail(session: Session, topic: EvoTopic, paper_id: UUID) -> dict | None:
    row = session.execute(
        select(EvoTopicPaper, EvoPaper)
        .join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic.id, EvoPaper.id == paper_id)
    ).first()
    if row is None:
        return None
    tp, p = row
    overrides = _overrides(session, topic.id)
    in_topic = {pp.id: (t, pp) for t, pp in _topic_rows(session, topic.id)}
    refs = [r for (r,) in session.execute(select(EvoCitation.cited_id).where(EvoCitation.citing_id == p.id))]
    citers = [c for (c,) in session.execute(select(EvoCitation.citing_id).where(EvoCitation.cited_id == p.id))]
    addresses = _strict(session, citing=[p.id], within=set(in_topic))
    addressed_by = _strict(session, cited=[p.id], within=set(in_topic))
    involved = {p.id} | {c.cited_id for c in addresses} | {c.citing_id for c in addressed_by}
    names = method_names(session, {i: in_topic[i][1].title for i in involved | set(refs) | set(citers)
                                   if i in in_topic})

    def node(i: UUID) -> dict:
        return _node(*in_topic[i], overrides.get(i), names.get(i))

    def neighbours(ids: list[UUID]) -> list[dict]:
        found = [node(i) for i in ids if i in in_topic]
        return sorted(found, key=lambda n: n["milestone_score"], reverse=True)[:10]

    def links(rows: list[EvoCitationContext], other: str) -> list[dict]:
        grouped: dict[UUID, list[EvoCitationContext]] = defaultdict(list)
        for ctx in rows:
            grouped[getattr(ctx, other)].append(ctx)
        out = [{"paper": node(pid), "evidence": [_evidence(c) for c in ctxs]} for pid, ctxs in grouped.items()]
        return sorted(out, key=lambda x: (x["paper"]["year"] or 0, -x["paper"]["milestone_score"]))

    full_text = (p.extra or {}).get("full_text") or {}
    gap_rows = session.execute(
        select(EvoGapStatement, EvoGapTheme.label)
        .outerjoin(EvoGapThemeMember, EvoGapThemeMember.gap_id == EvoGapStatement.id)
        .outerjoin(EvoGapTheme, (EvoGapTheme.id == EvoGapThemeMember.theme_id) & (EvoGapTheme.topic_id == topic.id))
        .where(EvoGapStatement.paper_id == p.id, EvoGapStatement.label == "gap")
    ).all()
    gaps = [{"sentence": g.sentence, "origin": g.origin, "section_type": g.section_type, "theme": theme,
             "stated_by": node(g.source_paper_id) if g.origin == "citing" and g.source_paper_id in in_topic else None}
            for g, theme in gap_rows if g.origin == "own" or g.source_paper_id in in_topic]
    loose_rows = session.execute(
        select(EvoLooseLink, EvoGapStatement.sentence, EvoChunk.text, EvoChunk.section_type)
        .join(EvoGapStatement, EvoLooseLink.gap_id == EvoGapStatement.id)
        .join(EvoChunk, EvoChunk.id == EvoLooseLink.chunk_id)
        .where(EvoGapStatement.paper_id == p.id, EvoLooseLink.score >= LOOSE_MIN_SCORE)
        .order_by(EvoLooseLink.score.desc())
    ).all()
    best: dict[UUID, dict] = {}
    for link, gap_sentence, chunk_text, section_type in loose_rows:
        if link.paper_id in in_topic and in_topic[link.paper_id][0].kind == "method" and link.paper_id not in best:
            best[link.paper_id] = {"paper": node(link.paper_id), "score": round(link.score, 3), "cites": link.cites,
                                   "gap": gap_sentence, "passage": chunk_text[:600], "section_type": section_type}
    return node(p.id) | {
        "abstract": p.abstract,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "openalex_year": p.openalex_year,
        "merged_ids": p.merged_ids or [],
        "builds_on": neighbours(refs),
        "built_upon_by": neighbours(citers),
        # Strict gap -> resolution links: earlier papers whose stated limitation this one takes on,
        # and later papers that take on this one's.
        "addresses": links(addresses, "cited_id"),
        "addressed_by": links(addressed_by, "citing_id"),
        "full_text": {k: full_text.get(k) for k in ("status", "sections", "contexts", "error") if k in full_text},
        # Phase 3: gaps stated in its own text or by later papers, and later papers whose text matches them.
        "gaps": gaps,
        "loose_matches": list(best.values())[:8],
        # OpenAlex's citations per year (athena.evolution.momentum); empty until fetched
        "citations_by_year": _citations_by_year(p),
    }


def _citations_by_year(p: EvoPaper) -> list[dict]:
    from athena.core.citation_gains import by_year, counts_of
    counts = counts_of(p)
    return by_year(counts, datetime.now(timezone.utc)) if counts else []


def topic_rising(session: Session, topic: EvoTopic, limit: int = 10, now: datetime | None = None) -> list[dict]:
    """The map's on-topic papers gaining citations fastest: the last twelve months against the twelve before
    (OpenAlex). Papers the corpus only holds because on-topic ones cite them (background like the Transformer, or
    neighbouring fields) are left out, as the milestones and the People view leave them out."""
    from athena.core.citation_gains import by_year, counts_of, rising_entry
    now = now or datetime.now(timezone.utc)
    rows = _topic_rows(session, topic.id)
    weight = TopicConfig.from_dict(topic.config).weights.relevance
    found = []
    for tp, p in rows:
        if weight > 0 and (tp.score_detail or {}).get("relevance", 0) <= 0:
            continue
        counts = counts_of(p)
        if counts and (entry := rising_entry(counts, now)):
            found.append((entry, tp, p, counts))
    found.sort(key=lambda f: (-f[0]["ratio"], -f[0]["last_12_months"]))
    found = found[:limit]
    overrides = _overrides(session, topic.id)
    names = method_names(session, {p.id: p.title for _, _, p, _ in found})
    return [_node(tp, p, overrides.get(p.id), names.get(p.id)) | entry | {"citations_by_year": by_year(counts, now)}
            for entry, tp, p, counts in found]
