"""
Database reads and writes for the research evolution feature.

Kept free of the graph libraries (igraph) so the API image, which installs
only requirements.api.txt, can import it.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from athena.core.models import (
    EvoChunk, EvoCitation, EvoCitationContext, EvoCrossLink, EvoGapStatement, EvoGapTheme, EvoGapThemeMember,
    EvoIdeaCheck, EvoLooseLink, EvoMainPathEdge, EvoMapQuestion, EvoMilestoneOverride, EvoPaper, EvoPaperNote,
    EvoReadingProgress, EvoSection, EvoTopic, EvoTopicPaper,
)
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.evolution.eras import find_era, on_topic_method, stored_eras
from athena.evolution.people import PeoplePaper, key_people, milestone_people, people_by_era
from athena.evolution.names import detect_method_name
from athena.evolution.reading_path import PathCandidate, build_path

if TYPE_CHECKING:
    from athena.evolution.corpus import Corpus
    from athena.evolution.fulltext import FullTextResult, KnownPaper, Tier2Paper
    from athena.evolution.milestones import TopicScores

OVERRIDE_ACTIONS = {"pin", "unpin", "reset"}
# Loose links below this cosine similarity are not shown. Stored links go down to the lane's floor (0.3),
# so the cutoff can change without recomputing them. Set by eye on samples of the first run: below 0.55
# matches were mostly unrelated, 0.65-0.70 about half right, 0.70 and above mostly right.
LOOSE_MIN_SCORE = float(os.getenv("EVOLUTION_LOOSE_MIN_SCORE", "0.68"))
# Citing-sentence labels that state a limitation of the cited paper; with ``attributed`` they make a strict link.
LIMITATION_LABELS = ("addresses_limitation", "criticises")
_BATCH = 500


def effective_milestone(auto: bool, override: str | None) -> bool:
    """A person's pin or unpin wins over the automatic pick."""
    if override == "pin":
        return True
    if override == "unpin":
        return False
    return auto


def _chunks(rows: list, size: int = _BATCH):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


# ── topics ─────────────────────────────────────────────────────────────


def upsert_topic(slug: str, name: str, aliases: list[str], description: str, seeds: list[dict],
                 config: dict, origin: str = "curated", query: str | None = None,
                 created_by: UUID | None = None) -> None:
    values = {"slug": slug, "name": name, "aliases": aliases, "description": description, "seeds": seeds,
              "config": config, "origin": origin, "query": query}
    with SessionLocal() as session:
        stmt = insert(EvoTopic).values(id=uuid4(), status="pending", created_by=created_by, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["slug"], set_=values)
        session.execute(stmt)
        session.commit()


def get_topic(session: Session, slug: str) -> EvoTopic | None:
    return session.execute(select(EvoTopic).where(EvoTopic.slug == slug)).scalar_one_or_none()


def set_topic_status(slug: str, status: str, status_detail: str | None = None, stats: dict | None = None) -> None:
    """``stats`` marks a finished build: it is stored, and ``built_at`` moves on so cached reads expire."""
    with SessionLocal() as session:
        topic = get_topic(session, slug)
        if topic is None:
            return
        topic.status = status
        topic.status_detail = status_detail
        if stats is not None:
            topic.build_stats = stats
            topic.built_at = datetime.now(timezone.utc)
        session.commit()


def delete_topic(session: Session, topic: EvoTopic) -> None:
    """Remove a topic with its scores, main path, overrides and gap themes. Papers are shared and stay."""
    # The database cascades to every topic table, in one statement rather than one per row.
    session.execute(delete(EvoTopic).where(EvoTopic.id == topic.id))
    session.commit()


def active_search_builds(session: Session) -> int:
    """Search-built topics waiting for, or in, their first build."""
    return session.execute(select(func.count()).select_from(EvoTopic).where(
        EvoTopic.origin == "search", EvoTopic.status.in_(["pending", "building"]))).scalar_one()


def slug_taken(session: Session, slug: str) -> bool:
    return session.execute(select(EvoTopic.id).where(EvoTopic.slug == slug)).first() is not None


def find_topic(session: Session, query: str) -> EvoTopic | None:
    """Match a free-text query against topic names and aliases ("lora fine-tuning" -> PEFT)."""
    q = " ".join(query.lower().replace("-", " ").split())
    if len(q) < 2:
        return None
    matches = []
    for topic in session.execute(select(EvoTopic)).scalars():
        for name in [topic.slug.replace("-", " "), topic.name, *(topic.aliases or [])]:
            n = " ".join(name.lower().replace("-", " ").split())
            if n == q or (len(n) >= 3 and f" {n} " in f" {q} ") or (len(q) >= 3 and q in n):
                # Prefer built topics, then the most specific (longest) matching name.
                matches.append((topic.status == "ready", len(n), topic))
    return max(matches, key=lambda m: m[:2])[2] if matches else None


def _overrides(session: Session, topic_id) -> dict:
    rows = session.execute(select(EvoMilestoneOverride).where(EvoMilestoneOverride.topic_id == topic_id)).scalars()
    return {o.paper_id: o for o in rows}


def _topic_rows(session: Session, topic_id) -> list[tuple[EvoTopicPaper, EvoPaper]]:
    return session.execute(
        select(EvoTopicPaper, EvoPaper)
        .join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic_id)
    ).all()


def list_topics(session: Session) -> list[dict]:
    out = []
    for topic in session.execute(select(EvoTopic).order_by(EvoTopic.name)).scalars():
        rows = _topic_rows(session, topic.id)
        overrides = _overrides(session, topic.id)
        milestones = sum(
            effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)
            for tp, p in rows
        )
        out.append(topic_summary(topic) | {"paper_count": len(rows), "milestone_count": milestones})
    return out


def topic_summary(topic: EvoTopic) -> dict:
    return {
        "slug": topic.slug,
        "name": topic.name,
        "aliases": topic.aliases or [],
        "description": topic.description,
        "status": topic.status,
        "status_detail": topic.status_detail,
        "built_at": topic.built_at.isoformat() if topic.built_at else None,
        "origin": getattr(topic, "origin", None) or "curated",
        "query": getattr(topic, "query", None),
        "build_stats": getattr(topic, "build_stats", None) or {},
        "created_by": str(topic.created_by) if getattr(topic, "created_by", None) else None,
    }


# ── build results ──────────────────────────────────────────────────────


def _merge_paper(oid: str, paper, existing: EvoPaper | None, now: datetime) -> dict:
    """Combine a build's view of a paper with what is stored; papers are shared across topics.

    Without this, the last topic built wins: building PEFT after object detection reset R-CNN's
    seed-corrected year and arXiv ID. Seed metadata wins, then a year read from an arXiv ID (it records
    first appearance exactly), then the earliest other year; links are only ever added.
    """
    w = paper.work
    title, year, year_source = w.title[:1000], paper.year, paper.year_source
    arxiv_id, oa_pdf_url, is_oa, abstract = w.arxiv_id, w.oa_pdf_url, w.is_oa, w.abstract
    s2_paper_id, s2_cited_by_count = w.s2_paper_id, w.s2_cited_by_count
    status = None
    if existing is not None:
        if existing.year_source == "seed" and year_source != "seed":
            title, year, year_source = existing.title, existing.year, existing.year_source
        elif year_source in ("seed", "arxiv"):
            pass
        elif existing.year_source == "arxiv" or (existing.year and (year is None or existing.year < year)):
            year, year_source = existing.year, existing.year_source
        arxiv_id = arxiv_id or existing.arxiv_id
        oa_pdf_url = oa_pdf_url or existing.oa_pdf_url
        is_oa = bool(is_oa or existing.is_oa)
        abstract = abstract or existing.abstract
        s2_paper_id = s2_paper_id or existing.s2_paper_id
        s2_cited_by_count = s2_cited_by_count or existing.s2_cited_by_count
        if existing.full_text_status in ("parsed", "failed"):
            status = existing.full_text_status  # a later phase already processed the full text
    return {
        "id": existing.id if existing is not None else uuid4(), "openalex_id": oid, "doi": w.doi,
        "arxiv_id": arxiv_id, "title": title, "abstract": abstract, "year": year, "year_source": year_source,
        "openalex_year": w.year, "venue": w.venue, "work_type": w.work_type, "authors": w.authors,
        # A build from an older cache entry may lack them; keep what a backfill stored.
        "authorships": w.authorships or getattr(existing, "authorships", None) or [],
        "cited_by_count": w.cited_by_count, "s2_paper_id": s2_paper_id, "s2_cited_by_count": s2_cited_by_count,
        "primary_topic": w.primary_topic, "is_oa": is_oa,
        "oa_pdf_url": oa_pdf_url,
        "full_text_status": status or ("available" if (arxiv_id or oa_pdf_url) else "unavailable"),
        "merged_ids": paper.merged_ids, "updated_at": now,
    }


def save_topic_build(slug: str, corpus: "Corpus", scores: "TopicScores") -> None:
    """Replace a topic's papers, scores and main path with a fresh build. Overrides are kept."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        topic = get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}")

        existing = {e.openalex_id: e for e in session.execute(
            select(EvoPaper).where(EvoPaper.openalex_id.in_(list(corpus.papers)))).scalars()}
        paper_rows = [_merge_paper(oid, p, existing.get(oid), now) for oid, p in corpus.papers.items()]
        for chunk in _chunks(paper_rows):
            stmt = insert(EvoPaper).values(chunk)
            updates = {c: stmt.excluded[c] for c in chunk[0] if c not in ("id", "openalex_id")}
            session.execute(stmt.on_conflict_do_update(index_elements=["openalex_id"], set_=updates))

        ids = dict(session.execute(
            select(EvoPaper.openalex_id, EvoPaper.id).where(EvoPaper.openalex_id.in_(list(corpus.papers)))
        ).all())

        session.execute(delete(EvoTopicPaper).where(EvoTopicPaper.topic_id == topic.id))
        tp_rows = []
        for oid, p in corpus.papers.items():
            s = scores.papers[oid]
            tp_rows.append({
                "id": uuid4(), "topic_id": topic.id, "paper_id": ids[oid], "role": p.role, "kind": s.kind,
                "in_degree": s.in_degree, "out_degree": s.out_degree, "pagerank": s.pagerank,
                "citation_percentile": s.citation_score, "specificity": s.specificity,
                "on_main_path": s.on_main_path, "named_method": s.named_method,
                "milestone_score": s.milestone_score, "is_milestone_auto": s.is_milestone_auto,
                "score_detail": s.detail,
            })
        for chunk in _chunks(tp_rows):
            session.execute(insert(EvoTopicPaper).values(chunk))

        cite_rows = [{"id": uuid4(), "citing_id": ids[a], "cited_id": ids[b],
                      "source": corpus.edge_sources.get((a, b), "openalex")} for a, b in corpus.edges]
        for chunk in _chunks(cite_rows):
            session.execute(insert(EvoCitation).values(chunk).on_conflict_do_nothing(constraint="uq_evo_citation"))

        session.execute(delete(EvoMainPathEdge).where(EvoMainPathEdge.topic_id == topic.id))
        mp_rows = [{"id": uuid4(), "topic_id": topic.id, "citing_id": ids[a], "cited_id": ids[b], "spc_weight": w}
                   for a, b, w in scores.main_path]
        if mp_rows:
            session.execute(insert(EvoMainPathEdge).values(mp_rows))
        session.commit()


# ── reads for the API ──────────────────────────────────────────────────


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


def labels_version(session: Session) -> str:
    """Changes whenever full text, labels or gap themes change, which happens without a topic rebuild."""
    count, last = session.execute(select(func.count(EvoCitationContext.id),
                                         func.max(EvoCitationContext.labelled_at))).one()
    themes = session.execute(select(func.max(EvoGapTheme.built_at))).scalar()
    stamp = lambda t: int(t.timestamp()) if t else 0  # noqa: E731
    return f"{count}-{stamp(last)}-{stamp(themes)}"


def method_names(session: Session, papers: dict[UUID, str]) -> dict[UUID, str]:
    """Names citing sentences use for each paper ({id: title} in, {id: name} out)."""
    if not papers:
        return {}
    mentions: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
    citers: dict[UUID, set[UUID]] = defaultdict(set)
    for cited, citing, words in session.execute(
            select(EvoCitationContext.cited_id, EvoCitationContext.citing_id, EvoCitationContext.mention)
            .where(EvoCitationContext.cited_id.in_(list(papers))).distinct()):
        citers[cited].add(citing)
        if words:
            mentions[cited].append((citing, words))
    out = {}
    for pid, pairs in mentions.items():
        name = detect_method_name(pairs, papers[pid], len(citers[pid]))
        if name:
            out[pid] = name
    return out


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
    """Milestones, main-path papers and seeds, then the highest-scoring papers up to ``limit``."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    names = method_names(session, {p.id: p.title for _, p in rows})
    nodes = [_node(tp, p, overrides.get(p.id), names.get(p.id)) for tp, p in rows]
    total = len(nodes)
    nodes.sort(key=lambda n: (n["is_milestone"] or n["on_main_path"] or n["role"] == "seed",
                              n["milestone_score"]), reverse=True)
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


def topic_eras(topic: EvoTopic, rows: list[tuple[EvoTopicPaper, EvoPaper]]) -> list[tuple[int, int]]:
    """The eras milestones were picked in, from a built topic's stored rows."""
    config = TopicConfig.from_dict(topic.config)
    return stored_eras(((tp.kind, tp.score_detail, p.year) for tp, p in rows), config.eras, config.max_era_years,
                       config.weights.relevance)


# ── reading path (E1) ──────────────────────────────────────────────────

NOTE_WHY = "why"


def current_notes(session: Session, topic: EvoTopic, paper_ids: list[UUID], kind: str = NOTE_WHY) -> dict[UUID, str]:
    """Notes written for the topic's current build; a rebuild makes the old ones stale."""
    if not paper_ids:
        return {}
    rows = session.execute(select(EvoPaperNote).where(
        EvoPaperNote.topic_id == topic.id, EvoPaperNote.paper_id.in_(paper_ids), EvoPaperNote.kind == kind)).scalars()
    return {n.paper_id: n.text for n in rows if n.built_at == topic.built_at}


def save_note(session: Session, topic: EvoTopic, paper_id: UUID, text: str, model: str,
              kind: str = NOTE_WHY) -> None:
    values = {"text": text, "model": model, "built_at": topic.built_at, "created_at": datetime.now(timezone.utc)}
    stmt = insert(EvoPaperNote).values(id=uuid4(), topic_id=topic.id, paper_id=paper_id, kind=kind, **values)
    session.execute(stmt.on_conflict_do_update(constraint="uq_evo_paper_note", set_=values))
    session.commit()


def read_papers(session: Session, user_id: UUID | None, paper_ids: list[UUID]) -> set[UUID]:
    if user_id is None or not paper_ids:
        return set()
    return set(session.execute(select(EvoReadingProgress.paper_id).where(
        EvoReadingProgress.user_id == user_id, EvoReadingProgress.paper_id.in_(paper_ids))).scalars())


def set_read(session: Session, user_id: UUID, paper_id: UUID, read: bool) -> bool:
    """Tick or untick a paper for a user. Returns False if the paper is unknown."""
    if session.get(EvoPaper, paper_id) is None:
        return False
    if read:
        session.execute(insert(EvoReadingProgress).values(user_id=user_id, paper_id=paper_id)
                        .on_conflict_do_nothing(index_elements=["user_id", "paper_id"]))
    else:
        session.execute(delete(EvoReadingProgress).where(EvoReadingProgress.user_id == user_id,
                                                         EvoReadingProgress.paper_id == paper_id))
    session.commit()
    return True


def reading_path(session: Session, topic: EvoTopic, user_id: UUID | None, n: int = 10) -> dict:
    """A survey, then milestones in year order: ``n`` papers, with notes, links between steps and read ticks."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    by_id = {p.id: (tp, p) for tp, p in rows}
    relevance_weight = TopicConfig.from_dict(topic.config).weights.relevance
    candidates = [
        PathCandidate(id=p.id, year=p.year, kind=tp.kind, milestone_score=tp.milestone_score or 0.0,
                      on_main_path=bool(tp.on_main_path),
                      # on_topic_method asks for a method paper too; here only the relevance counts
                      on_topic=on_topic_method("method", tp.score_detail, relevance_weight),
                      is_milestone=effective_milestone(tp.is_milestone_auto,
                                                       overrides[p.id].action if p.id in overrides else None))
        for tp, p in rows
    ]
    milestones = [c.id for c in candidates if c.is_milestone]
    surveys = {c.id: c for c in candidates if c.kind == "survey"}
    for citing, count in session.execute(
            select(EvoCitation.citing_id, func.count()).where(EvoCitation.citing_id.in_(list(surveys)),
                                                              EvoCitation.cited_id.in_(milestones))
            .group_by(EvoCitation.citing_id)):
        surveys[citing].milestones_cited = count
    survey, others, steps = build_path(candidates, n, topic_eras(topic, rows))
    path = ([survey] if survey else []) + steps
    ids = [c.id for c in path]
    names = method_names(session, {i: by_id[i][1].title for i in ids})
    notes = current_notes(session, topic, ids)
    read = read_papers(session, user_id, ids)
    position = {pid: i for i, pid in enumerate(ids)}
    cites: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
            EvoCitation.citing_id.in_(ids), EvoCitation.cited_id.in_(ids))):
        cites[citing].add(cited)
    fixes: dict[UUID, set[UUID]] = defaultdict(set)
    for ctx in _strict(session, citing=ids, cited=ids):
        fixes[ctx.citing_id].add(ctx.cited_id)

    def earlier(pid: UUID, targets: set[UUID]) -> list[int]:
        return sorted(position[t] + 1 for t in targets if position.get(t, len(ids)) < position[pid])

    def entry(c: PathCandidate) -> dict:
        tp, p = by_id[c.id]
        return _node(tp, p, overrides.get(c.id), names.get(c.id)) | {
            "position": position[c.id] + 1,
            "why": notes.get(c.id),
            "read": c.id in read,
            # Earlier steps this one cites, and earlier steps whose stated limitation it takes on (by number).
            "builds_on": earlier(c.id, cites.get(c.id, set())),
            "addresses": earlier(c.id, fixes.get(c.id, set())),
        }

    def other(c: PathCandidate) -> dict:
        tp, p = by_id[c.id]
        return _node(tp, p, overrides.get(c.id))

    return {
        "topic": topic_summary(topic),
        "n": n,
        "survey": entry(survey) if survey else None,
        "other_surveys": [other(c) for c in others],
        "steps": [entry(c) for c in steps],
        "read_count": len(read),
        "total": len(ids),
    }


def note_context(session: Session, topic: EvoTopic, paper_ids: list[UUID]) -> list[dict]:
    """What the note writer needs about each paper: title, year, name, abstract and the earlier papers in
    ``paper_ids`` it cites."""
    rows = {p.id: (tp, p) for tp, p in session.execute(
        select(EvoTopicPaper, EvoPaper).join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic.id, EvoPaper.id.in_(paper_ids))).all()}
    names = method_names(session, {pid: p.title for pid, (_, p) in rows.items()})
    cites: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
            EvoCitation.citing_id.in_(paper_ids), EvoCitation.cited_id.in_(paper_ids))):
        cites[citing].add(cited)
    out = []
    for i, pid in enumerate(paper_ids):
        if pid not in rows:
            continue
        tp, p = rows[pid]

        def label(other: UUID) -> str:
            _, q = rows[other]
            return f"{names.get(other) or q.title} ({q.year})"
        out.append({
            "paper_id": pid, "title": p.title, "year": p.year, "kind": tp.kind, "abstract": p.abstract,
            "name": names.get(pid) or tp.named_method,
            "builds_on": [label(o) for o in paper_ids[:i] if o in cites.get(pid, set()) and o in rows][-3:],
        })
    return out


# ── people (E8) ────────────────────────────────────────────────────────


def topic_people(session: Session, topic: EvoTopic) -> dict:
    """Key authors and labs per era and overall, and who introduced each milestone."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    weight = TopicConfig.from_dict(topic.config).weights.relevance
    on_topic = [(tp, p) for tp, p in rows if on_topic_method(tp.kind, tp.score_detail, weight)]
    milestones = {p.id for tp, p in rows
                  if effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)}
    names = method_names(session, {p.id: p.title for _, p in rows if p.id in milestones})

    def person_paper(tp: EvoTopicPaper, p: EvoPaper) -> PeoplePaper:
        return PeoplePaper(id=str(p.id), title=p.title, year=p.year, milestone_score=tp.milestone_score or 0.0,
                           is_milestone=p.id in milestones, named_method=names.get(p.id) or tp.named_method,
                           authorships=p.authorships or [], authors=p.authors or [])

    papers = [person_paper(tp, p) for tp, p in on_topic]
    # Milestones a person pinned although they are not on-topic method papers still had authors.
    pinned = [person_paper(tp, p) for tp, p in rows
              if p.id in milestones and not on_topic_method(tp.kind, tp.score_detail, weight)]
    with_ids = sum(bool(p.authorships) for p in papers)
    return {
        "topic": topic_summary(topic),
        "eras": people_by_era(papers, topic_eras(topic, rows)),
        "overall": key_people(papers),
        "milestones": milestone_people(papers + pinned),
        "papers": len(papers),
        "papers_with_ids": with_ids,  # the rest are told apart by name only
    }


# ── the feed and the maps (E5) ─────────────────────────────────────────


def map_membership(session: Session, paper_ids: list[UUID]) -> dict[UUID, list[dict]]:
    """Each paper's place in every built map: topic, milestone or not (pins applied), and its name."""
    if not paper_ids:
        return {}
    rows = session.execute(
        select(EvoTopicPaper, EvoTopic, EvoPaper)
        .join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id).join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.paper_id.in_(paper_ids), EvoTopic.built_at.isnot(None))).all()
    pins = {(o.topic_id, o.paper_id): o.action for o in session.execute(select(EvoMilestoneOverride).where(
        EvoMilestoneOverride.paper_id.in_(paper_ids))).scalars()}
    out: dict[UUID, list[dict]] = defaultdict(list)
    for tp, topic, p in rows:
        name = tp.named_method or ((p.cited_name or {}).get("name") if isinstance(p.cited_name, dict) else None)
        out[p.id].append({"topic": topic.slug, "topic_name": topic.name, "title": p.title, "year": p.year,
                          "named_method": name,
                          "milestone": effective_milestone(tp.is_milestone_auto, pins.get((topic.id, p.id)))})
    return out


def feed_place(session: Session, item_id: UUID) -> dict | None:
    """Where a feed item sits in the maps (when it is a map paper), and the milestones it cites."""
    from athena.core.models import ContentItem
    item = session.get(ContentItem, item_id)
    if item is None:
        return None
    places = []
    for p in session.execute(select(EvoPaper).where(EvoPaper.content_item_id == item_id)).scalars():
        for tp, topic in session.execute(
                select(EvoTopicPaper, EvoTopic).join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id)
                .where(EvoTopicPaper.paper_id == p.id, EvoTopic.built_at.isnot(None))).all():
            rows = _topic_rows(session, topic.id)
            override = _overrides(session, topic.id).get(p.id)
            rank = 1 + sum((other.milestone_score or 0) > (tp.milestone_score or 0) for other, _ in rows)
            era = find_era(p.year, topic_eras(topic, rows))
            in_topic = {q.id for _, q in rows}
            gaps = [g.sentence for g in session.execute(select(EvoGapStatement).where(
                EvoGapStatement.paper_id == p.id, EvoGapStatement.label == "gap",
                EvoGapStatement.origin == "own")).scalars()]
            fixes = {}
            for ctx in _strict(session, citing=[p.id], within=in_topic):
                if ctx.label == "addresses_limitation":
                    fixes.setdefault(ctx.cited_id, ctx.sentence)
            titles = dict(session.execute(
                select(EvoPaper.id, EvoPaper.title).where(EvoPaper.id.in_(list(fixes)))).all())
            loose = session.execute(select(func.count()).select_from(EvoLooseLink).where(
                EvoLooseLink.paper_id == p.id, EvoLooseLink.score >= LOOSE_MIN_SCORE)).scalar_one()
            places.append({
                "topic": topic_summary(topic), "paper_id": str(p.id), "kind": tp.kind, "year": p.year,
                "era": list(era) if era else None,
                "is_milestone": effective_milestone(tp.is_milestone_auto, override.action if override else None),
                "on_main_path": tp.on_main_path, "rank": rank, "of": len(rows),
                "gaps_stated": gaps[:5], "gaps_stated_count": len(gaps),
                "solves": [{"paper_id": str(pid), "title": titles.get(pid), "sentence": sentence}
                           for pid, sentence in fixes.items()][:5],
                "loose_matches": loose,
            })
    state = (item.extra_data or {}).get("evolution") or {}
    return {"item_id": str(item.id), "places": places, "cites": state.get("cites", []),
            "maps_cited": state.get("maps", {}), "references": state.get("references"),
            "checked_at": state.get("checked_at")}


def new_feed_papers(session: Session, days: int = 30, topic: str | None = None) -> list[dict]:
    """Recent feed papers that cite milestones, the ones citing the most first."""
    from athena.core.models import ContentItem
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for item in session.execute(select(ContentItem).where(ContentItem.published_at >= since,
                                                          ContentItem.extra_data.has_key("evolution"))).scalars():
        cites = [c for c in ((item.extra_data or {}).get("evolution") or {}).get("cites", [])
                 if topic is None or c["topic"] == topic]
        if cites:
            out.append({"id": str(item.id), "title": item.title, "url": item.url,
                        "published_at": item.published_at.isoformat(), "score": item.score, "cites": cites})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    out.sort(key=lambda x: len(x["cites"]), reverse=True)  # stable: newest first among equals
    return out


# ── idea checks (E2) ───────────────────────────────────────────────────


def _idea_check(c: EvoIdeaCheck, full: bool = True) -> dict:
    result = c.result or {}
    themes = result.get("themes") or []
    out = {"id": str(c.id), "idea": c.idea if full else c.idea[:240], "created_at": c.created_at.isoformat(),
           "papers": len(result.get("papers") or []), "themes": len(themes),
           "open_themes": sum(bool(t.get("open")) for t in themes)}
    return out | {"result": result} if full else out


def save_idea_check(session: Session, user_id: UUID, idea: str, result: dict) -> dict:
    check = EvoIdeaCheck(user_id=user_id, idea=idea, result=result, created_at=datetime.now(timezone.utc))
    session.add(check)
    session.commit()
    return _idea_check(check)


def list_idea_checks(session: Session, user_id: UUID, limit: int = 50) -> list[dict]:
    rows = session.execute(select(EvoIdeaCheck).where(EvoIdeaCheck.user_id == user_id)
                           .order_by(EvoIdeaCheck.created_at.desc()).limit(limit)).scalars()
    return [_idea_check(c, full=False) for c in rows]


def get_idea_check(session: Session, user_id: UUID, check_id: UUID) -> dict | None:
    """A user's own check; another user's is as good as missing."""
    check = session.get(EvoIdeaCheck, check_id)
    return _idea_check(check) if check is not None and check.user_id == user_id else None


def delete_idea_check(session: Session, user_id: UUID, check_id: UUID) -> bool:
    deleted = session.execute(delete(EvoIdeaCheck).where(EvoIdeaCheck.id == check_id,
                                                         EvoIdeaCheck.user_id == user_id)).rowcount
    session.commit()
    return bool(deleted)


# ── questions to a map (E3) ────────────────────────────────────────────


def save_map_question(user_id: UUID, topic_id: UUID, question: str, answer: str, sources: list[dict],
                      sections: list[str], input_tokens: int, output_tokens: int, model: str) -> UUID:
    """Runs after a streamed answer, so it opens its own session (the request's has closed)."""
    with SessionLocal() as session:
        row = EvoMapQuestion(user_id=user_id, topic_id=topic_id, question=question, answer=answer, sources=sources,
                             sections=sections, input_tokens=input_tokens, output_tokens=output_tokens, model=model,
                             created_at=datetime.now(timezone.utc))
        session.add(row)
        session.commit()
        return row.id


def map_questions(session: Session, user_id: UUID, topic_id: UUID, limit: int = 30) -> list[dict]:
    """A user's questions to one map, oldest first, so the page can show them as a conversation."""
    rows = list(session.execute(select(EvoMapQuestion).where(
        EvoMapQuestion.user_id == user_id, EvoMapQuestion.topic_id == topic_id)
        .order_by(EvoMapQuestion.created_at.desc()).limit(limit)).scalars())
    return [{"id": str(q.id), "question": q.question, "answer": q.answer, "sources": q.sources or [],
             "sections": q.sections or [], "created_at": q.created_at.isoformat()} for q in reversed(rows)]


def delete_map_question(session: Session, user_id: UUID, question_id: UUID | None = None,
                        topic_id: UUID | None = None) -> int:
    """One of a user's questions, or all of them for a topic."""
    stmt = delete(EvoMapQuestion).where(EvoMapQuestion.user_id == user_id)
    if question_id is not None:
        stmt = stmt.where(EvoMapQuestion.id == question_id)
    if topic_id is not None:
        stmt = stmt.where(EvoMapQuestion.topic_id == topic_id)
    deleted = session.execute(stmt).rowcount
    session.commit()
    return deleted


# ── links between maps (E7) ────────────────────────────────────────────


def maps_version(session: Session) -> str:
    """Changes when any map is built or deleted, or the cross-map pass finds links."""
    latest, count = session.execute(select(func.max(EvoTopic.built_at), func.count(EvoTopic.id))).one()
    links = session.execute(select(func.count(EvoCrossLink.id))).scalar()
    return f"{int(latest.timestamp()) if latest else 0}-{count}-{links}"


def pending_cross(session: Session, limit: int) -> list[tuple[EvoGapStatement, int | None]]:
    """Embedded gap statements not yet searched against other maps' papers, with the stating paper's year."""
    source = aliased(EvoPaper)
    return session.execute(
        select(EvoGapStatement, source.year).join(source, EvoGapStatement.source_paper_id == source.id)
        .where(EvoGapStatement.label == "gap", EvoGapStatement.embedded_at.isnot(None),
               EvoGapStatement.cross_checked_at.is_(None)).limit(limit)).all()


def paper_topic_kinds(session: Session, paper_ids: list[UUID]) -> dict[UUID, dict[str, str]]:
    """Paper -> {topic id: kind} for every topic it is in, read fresh (the chunks' topic payload can be stale)."""
    out: dict[UUID, dict[str, str]] = defaultdict(dict)
    for pid, tid, kind in session.execute(select(EvoTopicPaper.paper_id, EvoTopicPaper.topic_id, EvoTopicPaper.kind)
                                          .where(EvoTopicPaper.paper_id.in_(paper_ids))):
        out[pid][str(tid)] = kind
    return out


def save_cross_links(session: Session, gap_id: UUID, links: list[dict]) -> None:
    """Replace a gap statement's cross-map links. ``links``: [{paper_id, chunk_id, score}]."""
    session.execute(delete(EvoCrossLink).where(EvoCrossLink.gap_id == gap_id))
    if links:
        session.execute(insert(EvoCrossLink).values([{"id": uuid4(), "gap_id": gap_id, **link} for link in links]))


def topic_links(session: Session, topic: EvoTopic, limit: int = 40) -> dict:
    """How this map connects to the others: papers they share, milestones one borrows from the other, and
    the other maps' papers whose text matches this map's gaps."""
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

    # Gaps of this map that another map's papers may address (found by the GPU lane's cross-map pass).
    cross = []
    theme_of = {g: t for g, t in session.execute(
        select(EvoGapThemeMember.gap_id, EvoGapTheme).join(EvoGapTheme, EvoGapThemeMember.theme_id == EvoGapTheme.id)
        .where(EvoGapTheme.topic_id == topic.id)).all()}
    if theme_of:
        best: dict[tuple[UUID, UUID], tuple] = {}
        for link, gap, paper, chunk_text, section_type in session.execute(
                select(EvoCrossLink, EvoGapStatement, EvoPaper, EvoChunk.text, EvoChunk.section_type)
                .join(EvoGapStatement, EvoCrossLink.gap_id == EvoGapStatement.id)
                .join(EvoPaper, EvoCrossLink.paper_id == EvoPaper.id)
                .join(EvoChunk, EvoChunk.id == EvoCrossLink.chunk_id)
                .where(EvoCrossLink.gap_id.in_(list(theme_of)), EvoCrossLink.score >= LOOSE_MIN_SCORE)):
            key = (theme_of[gap.id].id, paper.id)
            if key not in best or link.score > best[key][0].score:
                best[key] = (link, gap, paper, chunk_text, section_type)
        maps_of = paper_topic_kinds(session, list({k[1] for k in best}))
        for (_, pid), (link, gap, paper, text, section_type) in sorted(best.items(), key=lambda kv: -kv[1][0].score):
            theme = theme_of[gap.id]
            cross.append({
                "theme": {"id": str(theme.id), "label": theme.label, "status": theme.status},
                "gap": gap.sentence, "score": round(link.score, 3),
                "paper": {"id": str(pid), "title": paper.title, "year": paper.year, "named_method": name_of(paper)},
                "maps": [{"topic": topics[UUID(t)].slug, "topic_name": topics[UUID(t)].name}
                         for t in maps_of.get(pid, {}) if UUID(t) in topics],
                "passage": text[:600], "section_type": section_type,
            })
    return {
        "topic": topic_summary(topic),
        "shared": {"total": len(shared),
                   "papers": [mini(pid) | {"elsewhere": elsewhere[pid]} for pid in shared[:limit]]},
        "borrowed": [mini(pid, info[pid].title, info[pid].year, name_of(info[pid]))
                     | {"from": milestones_elsewhere[pid], "citing_papers": n}
                     for pid, n in borrowed_ids if pid in info],
        "lent": [mini(pid) | {"citing_papers": n, "by": dict(sorted(lent_by[pid].items(), key=lambda kv: -kv[1]))}
                 for pid, n in lent_ids],
        "cross_gaps": cross[:30],
        "cross_min_score": LOOSE_MIN_SCORE,
    }


# ── names citing papers use (E9) ───────────────────────────────────────


def save_cited_name(session: Session, paper_id: UUID, value: dict) -> None:
    session.execute(update(EvoPaper).where(EvoPaper.id == paper_id).values(cited_name=value))
    session.commit()


def cited_names_fetched_since(session: Session, paper_ids: list[UUID], days: int) -> set[UUID]:
    """Papers whose cited name was fetched in the last ``days`` days."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = set()
    for pid, value in session.execute(select(EvoPaper.id, EvoPaper.cited_name).where(
            EvoPaper.id.in_(paper_ids), EvoPaper.cited_name.isnot(None))):
        try:
            if datetime.fromisoformat(value["fetched_at"]).timestamp() >= cutoff:
                out.add(pid)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def cited_names(openalex_ids: list[str]) -> dict[str, str]:
    """OpenAlex ID -> the name citing papers use, for papers where one was found."""
    with SessionLocal() as session:
        rows = session.execute(select(EvoPaper.openalex_id, EvoPaper.cited_name).where(
            EvoPaper.openalex_id.in_(openalex_ids), EvoPaper.cited_name.isnot(None))).all()
    return {oid: v["name"] for oid, v in rows if isinstance(v, dict) and v.get("name")}


# ── exports (E6) ───────────────────────────────────────────────────────


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


def milestone_ids(session: Session, topic: EvoTopic) -> list[UUID]:
    """The topic's milestones (pins applied), oldest first."""
    overrides = _overrides(session, topic.id)
    rows = [(p.year or 0, p.id) for tp, p in _topic_rows(session, topic.id)
            if effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)]
    return [pid for _, pid in sorted(rows)]


def gap_export_rows(session: Session, topic: EvoTopic) -> list[dict]:
    """Every statement in the topic's gap themes, with its theme, for the CSV export."""
    in_topic = {p.id: p for _, p in _topic_rows(session, topic.id)}
    order = {"persisting": 0, "new": 1, "addressed": 2, "quiet": 3}
    themes = sorted(session.execute(select(EvoGapTheme).where(EvoGapTheme.topic_id == topic.id)).scalars(),
                    key=lambda t: (order.get(t.status, 4), -t.size))
    members: dict[UUID, list[EvoGapStatement]] = defaultdict(list)
    for theme_id, gap in session.execute(
            select(EvoGapThemeMember.theme_id, EvoGapStatement)
            .join(EvoGapStatement, EvoGapThemeMember.gap_id == EvoGapStatement.id)
            .where(EvoGapThemeMember.theme_id.in_([t.id for t in themes]))):
        members[theme_id].append(gap)
    out = []
    for t in themes:
        for g in sorted(members.get(t.id, []), key=lambda g: (in_topic[g.source_paper_id].year or 0
                                                              if g.source_paper_id in in_topic else 0)):
            paper, source = in_topic.get(g.paper_id), in_topic.get(g.source_paper_id)
            out.append({
                "theme": t.label, "status": t.status, "first_year": t.first_year, "last_year": t.last_year,
                "theme_size": t.size, "statement": g.sentence, "origin": g.origin, "section": g.section_type,
                "paper": paper.title if paper else None, "paper_year": paper.year if paper else None,
                "stated_by": source.title if source and g.origin == "citing" else None,
                "stated_by_year": source.year if source and g.origin == "citing" else None,
            })
    return out


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
    }


def set_override(session: Session, topic: EvoTopic, paper_id: UUID, action: str, note: str | None) -> bool:
    """Pin, unpin, or reset a milestone. Returns False if the paper is not in the topic."""
    if action not in OVERRIDE_ACTIONS:
        raise ValueError(f"action must be one of {sorted(OVERRIDE_ACTIONS)}")
    in_topic = session.execute(
        select(EvoTopicPaper.id).where(EvoTopicPaper.topic_id == topic.id, EvoTopicPaper.paper_id == paper_id)
    ).first()
    if in_topic is None:
        return False
    if action == "reset":
        session.execute(delete(EvoMilestoneOverride).where(
            EvoMilestoneOverride.topic_id == topic.id, EvoMilestoneOverride.paper_id == paper_id))
    else:
        stmt = insert(EvoMilestoneOverride).values(id=uuid4(), topic_id=topic.id, paper_id=paper_id,
                                                   action=action, note=note)
        session.execute(stmt.on_conflict_do_update(
            constraint="uq_evo_milestone_override",
            set_={"action": action, "note": note, "created_at": datetime.now(timezone.utc)},
        ))
    session.commit()
    return True


# ── Tier 2 full text ───────────────────────────────────────────────────


def tier2_ids(session: Session, topic: EvoTopic, successors: int) -> set[UUID]:
    """Milestones (pins included), main-path papers, and each milestone's ``successors`` strongest citers.

    Successors are on-topic method papers in the topic, ranked by milestone score.
    """
    overrides = _overrides(session, topic.id)
    rows = {p.id: tp for tp, p in _topic_rows(session, topic.id)}
    milestones = {pid for pid, tp in rows.items()
                  if effective_milestone(tp.is_milestone_auto, overrides[pid].action if pid in overrides else None)}
    main = {pid for pid, tp in rows.items() if tp.on_main_path}
    by_milestone: dict[UUID, list[UUID]] = defaultdict(list)
    for citing, cited in session.execute(
            select(EvoCitation.citing_id, EvoCitation.cited_id).where(EvoCitation.cited_id.in_(milestones))):
        tp = rows.get(citing)
        if tp is not None and tp.kind == "method" and (tp.score_detail or {}).get("relevance", 0) > 0:
            by_milestone[cited].append(citing)
    picked = milestones | main
    for citers in by_milestone.values():
        picked.update(sorted(citers, key=lambda c: rows[c].milestone_score, reverse=True)[:successors])
    return picked


def tier2_papers(session: Session, ids: set[UUID], reparse: bool = False) -> list["Tier2Paper"]:
    """The papers in ``ids`` still needing full text (all of them with ``reparse``), with their known refs."""
    from athena.evolution.fulltext import Tier2Paper  # fulltext needs igraph, which the API image lacks
    query = select(EvoPaper).where(EvoPaper.id.in_(ids))
    if not reparse:
        # Never tried, or tried without a PDF and an arXiv ID has turned up since (a rebuild can
        # bring one from Semantic Scholar; a download that timed out is retried too).
        query = query.where(EvoPaper.full_text_status.in_(["available", "unavailable"]),
                            or_(EvoPaper.extra.is_(None), ~EvoPaper.extra.has_key("full_text"),
                                EvoPaper.arxiv_id.isnot(None)))
    papers = list(session.execute(query).scalars())
    refs: dict[UUID, list[UUID]] = defaultdict(list)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id)
                                         .where(EvoCitation.citing_id.in_([p.id for p in papers]))):
        refs[citing].append(cited)
    return [Tier2Paper(id=p.id, openalex_id=p.openalex_id, title=p.title, arxiv_id=p.arxiv_id,
                       oa_pdf_url=p.oa_pdf_url, s2_paper_id=p.s2_paper_id, known_refs=refs[p.id]) for p in papers]


def known_papers(session: Session) -> list["KnownPaper"]:
    from athena.evolution.fulltext import KnownPaper
    rows = session.execute(select(EvoPaper.id, EvoPaper.title, EvoPaper.year, EvoPaper.arxiv_id, EvoPaper.doi,
                                  EvoPaper.s2_paper_id))
    return [KnownPaper(id=i, title=t, year=y, arxiv_id=a, doi=d, s2_paper_id=s2) for i, t, y, a, d, s2 in rows]


def save_full_text(result: "FullTextResult") -> list[UUID]:
    """Store one paper's sections, chunks and citing sentences.

    Chunk IDs are stable across re-parses, so unchanged chunks keep their embeddings and contexts
    keep their labels. Returns embedded chunk IDs that no longer exist, for removal from Qdrant.
    """
    from athena.evolution.fulltext import cue_words, sentence_hash
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        stale: list[UUID] = []
        if result.status == "parsed":
            embedded = dict(session.execute(select(EvoChunk.id, EvoChunk.embedded_at)
                                            .where(EvoChunk.paper_id == result.paper_id)).all())
            new_ids = {c["id"] for c in result.chunks}
            stale = [cid for cid, at in embedded.items() if at is not None and cid not in new_ids]
            session.execute(delete(EvoSection).where(EvoSection.paper_id == result.paper_id))
            session.flush()
            if result.sections:
                session.execute(insert(EvoSection).values(result.sections))
            rows = [c | {"embedded_at": embedded.get(c["id"])} for c in result.chunks]
            for chunk in _chunks(rows):
                session.execute(insert(EvoChunk).values(chunk))

        context_rows = {}
        for c in result.contexts:
            key = (c.cited_id, sentence_hash(c.sentence))
            context_rows.setdefault(key, {
                "id": uuid4(), "citing_id": result.paper_id, "cited_id": c.cited_id, "source": c.source,
                "section_type": c.section_type, "sentence": c.sentence[:4000], "sentence_hash": key[1],
                "marked": c.marked[:4100] if c.marked else None, "mention": c.mention,
                "cues": cue_words(c.sentence), "s2_intents": c.s2_intents,
            })
        sources = {c.source for c in result.contexts} or {"grobid" if result.status == "parsed" else "s2"}
        existing = session.execute(select(EvoCitationContext.id, EvoCitationContext.cited_id,
                                          EvoCitationContext.sentence_hash)
                                   .where(EvoCitationContext.citing_id == result.paper_id,
                                          EvoCitationContext.source.in_(sources))).all()
        gone = [cid for cid, cited, h in existing if (cited, h) not in context_rows]
        if gone:
            session.execute(delete(EvoCitationContext).where(EvoCitationContext.id.in_(gone)))
        for chunk in _chunks(list(context_rows.values())):
            # A sentence already stored keeps its label; what the parser derives from it is refreshed.
            stmt = insert(EvoCitationContext).values(chunk)
            session.execute(stmt.on_conflict_do_update(
                constraint="uq_evo_citation_context",
                set_={c: stmt.excluded[c] for c in ("section_type", "marked", "mention", "cues")}))

        if result.status == "parsed":
            _save_own_gaps(session, result.paper_id, result.gaps)

        if result.new_refs:
            session.execute(insert(EvoCitation).values([
                {"id": uuid4(), "citing_id": result.paper_id, "cited_id": cited, "source": "grobid"}
                for cited in result.new_refs]).on_conflict_do_nothing(constraint="uq_evo_citation"))

        paper = session.get(EvoPaper, result.paper_id)
        if result.status in ("parsed", "failed"):
            paper.full_text_status = result.status
        detail = result.detail | {"status": result.status, "at": now.isoformat()}
        paper.extra = {**(paper.extra or {}), "full_text": detail}
        session.commit()
        return stale


def _save_own_gaps(session: Session, paper_id: UUID, gaps: list[tuple[str, str]]) -> None:
    """Gap candidates from a paper's own text; candidates already labelled keep their label."""
    from athena.evolution.fulltext import sentence_hash
    rows = {}
    for section_type, sentence in gaps:
        h = sentence_hash(sentence)
        rows.setdefault(h, {"id": uuid4(), "paper_id": paper_id, "source_paper_id": paper_id, "origin": "own",
                            "section_type": section_type, "sentence": sentence[:4000], "sentence_hash": h})
    session.execute(delete(EvoGapStatement).where(
        EvoGapStatement.source_paper_id == paper_id, EvoGapStatement.origin == "own",
        EvoGapStatement.sentence_hash.notin_(list(rows) or [""])))
    for chunk in _chunks(list(rows.values())):
        stmt = insert(EvoGapStatement).values(chunk)
        session.execute(stmt.on_conflict_do_update(constraint="uq_evo_gap_statement",
                                                   set_={"section_type": stmt.excluded.section_type}))


def pending_chunks(session: Session, limit: int) -> list[tuple[EvoChunk, EvoPaper, EvoSection]]:
    return session.execute(
        select(EvoChunk, EvoPaper, EvoSection)
        .join(EvoPaper, EvoChunk.paper_id == EvoPaper.id)
        .join(EvoSection, EvoChunk.section_id == EvoSection.id)
        .where(EvoChunk.embedded_at.is_(None))
        .order_by(EvoChunk.paper_id, EvoChunk.position)
        .limit(limit)
    ).all()


def mark_embedded(session: Session, chunk_ids: list[UUID]) -> None:
    session.execute(update(EvoChunk).where(EvoChunk.id.in_(chunk_ids))
                    .values(embedded_at=datetime.now(timezone.utc)))
    session.commit()


def paper_topics(session: Session, paper_ids: list[UUID]) -> dict[UUID, list[str]]:
    """Topic slugs each paper belongs to, for Qdrant payloads."""
    out: dict[UUID, list[str]] = defaultdict(list)
    for pid, slug in session.execute(select(EvoTopicPaper.paper_id, EvoTopic.slug)
                                     .join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id)
                                     .where(EvoTopicPaper.paper_id.in_(paper_ids))):
        out[pid].append(slug)
    return out


def pending_contexts(session: Session, cited_ids: set[UUID],
                     limit: int) -> list[tuple[EvoCitationContext, str, str]]:
    """Unlabelled citing sentences with a contrast cue whose cited paper is in Tier 2, with both titles."""
    citing, cited = aliased(EvoPaper), aliased(EvoPaper)
    return session.execute(
        select(EvoCitationContext, citing.title, cited.title)
        .join(citing, EvoCitationContext.citing_id == citing.id)
        .join(cited, EvoCitationContext.cited_id == cited.id)
        .where(EvoCitationContext.label.is_(None), EvoCitationContext.cited_id.in_(cited_ids),
               EvoCitationContext.cues != [])
        .order_by(EvoCitationContext.citing_id)
        .limit(limit)
    ).all()


def unconfirmed_strict(session: Session, model_tag: str, limit: int) -> list[tuple[EvoCitationContext, str, str]]:
    """Strict links labelled by an earlier classifier version, with both titles."""
    citing, cited = aliased(EvoPaper), aliased(EvoPaper)
    return session.execute(
        select(EvoCitationContext, citing.title, cited.title)
        .join(citing, EvoCitationContext.citing_id == citing.id)
        .join(cited, EvoCitationContext.cited_id == cited.id)
        .where(EvoCitationContext.label.in_(LIMITATION_LABELS), EvoCitationContext.attributed.is_(True),
               or_(EvoCitationContext.model.is_(None), EvoCitationContext.model != model_tag))
        .limit(limit)
    ).all()


def save_labels(session: Session, labels: list[dict]) -> None:
    """``labels``: [{id, label, attributed, model}]."""
    now = datetime.now(timezone.utc)
    for row in labels:
        session.execute(update(EvoCitationContext).where(EvoCitationContext.id == row["id"]).values(
            label=row["label"], attributed=row["attributed"], model=row["model"], labelled_at=now))
    session.commit()


def all_tier2_ids(session: Session) -> set[UUID]:
    ids: set[UUID] = set()
    for topic in session.execute(select(EvoTopic).where(EvoTopic.status == "ready")).scalars():
        ids |= tier2_ids(session, topic, TopicConfig.from_dict(topic.config).tier2_successors)
    return ids


# ── Phase 3: gaps and loose links ──────────────────────────────────────


def sync_citing_gaps(session: Session) -> int:
    """Make every strict link a gap statement about the cited paper, and drop ones no longer strict."""
    from athena.evolution.fulltext import sentence_hash
    strict = {c.id: c for c in session.execute(
        select(EvoCitationContext).where(EvoCitationContext.label.in_(LIMITATION_LABELS),
                                         EvoCitationContext.attributed.is_(True))).scalars()}
    session.execute(delete(EvoGapStatement).where(
        EvoGapStatement.origin == "citing", EvoGapStatement.context_id.notin_(list(strict) or [uuid4()])))
    rows = [{"id": uuid4(), "paper_id": c.cited_id, "source_paper_id": c.citing_id, "origin": "citing",
             "context_id": c.id, "section_type": c.section_type, "sentence": c.sentence[:4000],
             "sentence_hash": sentence_hash(c.sentence), "label": "gap", "model": c.model,
             "labelled_at": c.labelled_at} for c in strict.values()]
    for chunk in _chunks(rows):
        session.execute(insert(EvoGapStatement).values(chunk).on_conflict_do_nothing(constraint="uq_evo_gap_statement"))
    session.commit()
    return len(rows)


def pending_gap_candidates(session: Session, limit: int) -> list[tuple[EvoGapStatement, str]]:
    return session.execute(
        select(EvoGapStatement, EvoPaper.title)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.label.is_(None))
        .order_by(EvoGapStatement.source_paper_id)
        .limit(limit)
    ).all()


def save_gap_labels(session: Session, labels: list[dict]) -> None:
    """``labels``: [{id, label, model}]."""
    now = datetime.now(timezone.utc)
    for row in labels:
        session.execute(update(EvoGapStatement).where(EvoGapStatement.id == row["id"]).values(
            label=row["label"], model=row["model"], labelled_at=now))
    session.commit()


def pending_gap_vectors(session: Session, limit: int) -> list[tuple[EvoGapStatement, int | None]]:
    """Gap statements without a vector, with the year the stating paper appeared."""
    return session.execute(
        select(EvoGapStatement, EvoPaper.year)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.label == "gap", EvoGapStatement.embedded_at.is_(None))
        .limit(limit)
    ).all()


def mark_gaps(session: Session, gap_ids: list[UUID], column: str) -> None:
    session.execute(update(EvoGapStatement).where(EvoGapStatement.id.in_(gap_ids))
                    .values({column: datetime.now(timezone.utc)}))
    session.commit()


def pending_loose(session: Session, limit: int) -> list[tuple[EvoGapStatement, int | None]]:
    """Embedded gap statements whose loose links have not been searched."""
    return session.execute(
        select(EvoGapStatement, EvoPaper.year)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.embedded_at.isnot(None), EvoGapStatement.loose_checked_at.is_(None))
        .limit(limit)
    ).all()


def cited_by(session: Session, paper_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    """{paper: papers citing it}, for flagging loose links that coincide with a citation."""
    out: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id)
                                         .where(EvoCitation.cited_id.in_(paper_ids))):
        out[cited].add(citing)
    return out


def save_loose_links(session: Session, gap_id: UUID, links: list[dict]) -> None:
    """Replace a gap statement's loose links. ``links``: [{paper_id, chunk_id, score, cites}]."""
    session.execute(delete(EvoLooseLink).where(EvoLooseLink.gap_id == gap_id))
    if links:
        session.execute(insert(EvoLooseLink).values([{"id": uuid4(), "gap_id": gap_id, **link} for link in links]))


def topic_gap_rows(session: Session, topic: EvoTopic) -> list[dict]:
    """Gap statements about papers in the topic, stated by papers in the topic, with years and labels."""
    in_topic = {p.id: p for _, p in _topic_rows(session, topic.id)}
    source = aliased(EvoPaper)
    rows = session.execute(
        select(EvoGapStatement, source.year, EvoCitationContext.label)
        .join(source, EvoGapStatement.source_paper_id == source.id)
        .outerjoin(EvoCitationContext, EvoGapStatement.context_id == EvoCitationContext.id)
        .where(EvoGapStatement.label == "gap", EvoGapStatement.embedded_at.isnot(None),
               EvoGapStatement.paper_id.in_(list(in_topic)), EvoGapStatement.source_paper_id.in_(list(in_topic)))
    ).all()
    return [{"id": g.id, "paper_id": g.paper_id, "source_paper_id": g.source_paper_id, "origin": g.origin,
             "sentence": g.sentence, "section_type": g.section_type, "year": year,
             "fix": context_label == "addresses_limitation"} for g, year, context_label in rows]


def save_themes(topic_id: UUID, themes: list[dict]) -> None:
    """Replace a topic's gap themes. ``themes``: [{label, size, yearly, first_year, last_year, status, detail,
    members}]."""
    with SessionLocal() as session:
        session.execute(delete(EvoGapTheme).where(EvoGapTheme.topic_id == topic_id))
        for t in themes:
            theme_id = uuid4()
            session.execute(insert(EvoGapTheme).values(
                id=theme_id, topic_id=topic_id, **{k: v for k, v in t.items() if k != "members"}))
            session.execute(insert(EvoGapThemeMember).values([{"theme_id": theme_id, "gap_id": g}
                                                              for g in t["members"]]))
        session.commit()


def topic_gaps(session: Session, topic: EvoTopic, examples: int = 3) -> dict:
    """The topic's gap themes, persisting ones first, each with yearly counts, papers and example sentences."""
    overrides = _overrides(session, topic.id)
    rows = {p.id: (tp, p) for tp, p in _topic_rows(session, topic.id)}
    themes = list(session.execute(select(EvoGapTheme).where(EvoGapTheme.topic_id == topic.id)).scalars())
    members: dict[UUID, list[EvoGapStatement]] = defaultdict(list)
    for theme_id, gap in session.execute(
            select(EvoGapThemeMember.theme_id, EvoGapStatement)
            .join(EvoGapStatement, EvoGapThemeMember.gap_id == EvoGapStatement.id)
            .where(EvoGapThemeMember.theme_id.in_([t.id for t in themes]))):
        members[theme_id].append(gap)
    loose: dict[UUID, list[EvoLooseLink]] = defaultdict(list)
    gap_ids = [g.id for gs in members.values() for g in gs]
    for link in session.execute(select(EvoLooseLink).where(EvoLooseLink.gap_id.in_(gap_ids),
                                                           EvoLooseLink.score >= LOOSE_MIN_SCORE)).scalars():
        loose[link.gap_id].append(link)
    names = method_names(session, {pid: p.title for pid, (_, p) in rows.items()})
    # Papers of other maps whose text matches the theme's statements (the GPU lane's cross-map pass).
    cross: dict[UUID, dict[UUID, float]] = defaultdict(dict)
    for link in session.execute(select(EvoCrossLink).where(EvoCrossLink.gap_id.in_(gap_ids),
                                                           EvoCrossLink.score >= LOOSE_MIN_SCORE)).scalars():
        cross[link.gap_id][link.paper_id] = max(link.score, cross[link.gap_id].get(link.paper_id, 0.0))
    cross_ids = list({pid for links in cross.values() for pid in links})
    cross_titles = {pid: (title, year) for pid, title, year in session.execute(
        select(EvoPaper.id, EvoPaper.title, EvoPaper.year).where(EvoPaper.id.in_(cross_ids)))} if cross_ids else {}
    cross_maps: dict[UUID, list[str]] = defaultdict(list)
    for pid, name in session.execute(select(EvoTopicPaper.paper_id, EvoTopic.name).join(
            EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id).where(EvoTopicPaper.paper_id.in_(cross_ids))):
        cross_maps[pid].append(name)

    def mini(pid) -> dict | None:
        if pid not in rows:
            return None
        tp, p = rows[pid]
        action = overrides[pid].action if pid in overrides else None
        return {"id": str(pid), "title": p.title, "year": p.year, "named_method": names.get(pid) or tp.named_method,
                "is_milestone": effective_milestone(tp.is_milestone_auto, action)}

    out = []
    for t in themes:
        gs = members.get(t.id, [])
        # Examples: own statements first (the paper on its own gap), then the most recent.
        picks = sorted(gs, key=lambda g: (g.origin != "own", -(rows[g.source_paper_id][1].year or 0)
                                          if g.source_paper_id in rows else 0))[:examples]
        candidates: dict[UUID, float] = {}
        for g in gs:
            for link in loose.get(g.id, []):
                if link.paper_id in rows and rows[link.paper_id][0].kind == "method":
                    candidates[link.paper_id] = max(link.score, candidates.get(link.paper_id, 0.0))
        detail = t.detail or {}
        elsewhere: dict[UUID, float] = {}
        for g in gs:
            for pid, score in cross.get(g.id, {}).items():
                elsewhere[pid] = max(score, elsewhere.get(pid, 0.0))
        out.append({
            "id": str(t.id), "label": t.label, "size": t.size, "status": t.status,
            "first_year": t.first_year, "last_year": t.last_year,
            "yearly": [{"year": int(y), "count": n} for y, n in sorted((t.yearly or {}).items())],
            "own": detail.get("own", 0), "citing": detail.get("citing", 0),
            "papers": [m for m in (mini(UUID(pid)) for pid in detail.get("papers", [])) if m],
            "fixed_by": [m for m in (mini(UUID(pid)) for pid in detail.get("fixed_by", [])) if m],
            "examples": [{"sentence": g.sentence, "origin": g.origin, "section_type": g.section_type,
                          "paper": mini(g.paper_id), "stated_by": mini(g.source_paper_id)} for g in picks],
            "loose_candidates": [{"paper": mini(pid), "score": round(score, 3)}
                                 for pid, score in sorted(candidates.items(), key=lambda kv: -kv[1])[:5]],
            "cross_candidates": [{"paper": {"id": str(pid), "title": cross_titles[pid][0],
                                            "year": cross_titles[pid][1]},
                                  "maps": cross_maps.get(pid, []), "score": round(score, 3)}
                                 for pid, score in sorted(elsewhere.items(), key=lambda kv: -kv[1])[:3]
                                 if pid in cross_titles],
        })
    order = {"persisting": 0, "new": 1, "addressed": 2, "quiet": 3}
    out.sort(key=lambda t: (order.get(t["status"], 3), -t["size"]))
    latest = max((t.detail or {}).get("latest_topic_year") or 0 for t in themes) if themes else None
    return {"topic": topic_summary(topic), "latest_year": latest or None, "themes": out,
            "loose_min_score": LOOSE_MIN_SCORE}


def pending_abstracts(session: Session, limit: int) -> list[EvoPaper]:
    """Topic papers whose title and abstract are not yet in Qdrant's paper_abstracts (Tier 1)."""
    return list(session.execute(
        select(EvoPaper).where(EvoPaper.abstract_embedded_at.is_(None),
                               EvoPaper.id.in_(select(EvoTopicPaper.paper_id)))
        .limit(limit)).scalars())


def mark_abstracts(session: Session, paper_ids: list[UUID]) -> None:
    session.execute(update(EvoPaper).where(EvoPaper.id.in_(paper_ids))
                    .values(abstract_embedded_at=datetime.now(timezone.utc)))
    session.commit()


def forget_vectors(session: Session) -> None:
    """Mark every chunk, gap statement and abstract as not embedded, and drop the loose and cross-map links.

    For a switch of embedding model: the next GPU lane embeds everything again and rebuilds the themes.
    """
    session.execute(update(EvoChunk).values(embedded_at=None))
    session.execute(update(EvoGapStatement).values(embedded_at=None, loose_checked_at=None, cross_checked_at=None))
    session.execute(update(EvoPaper).values(abstract_embedded_at=None))
    session.execute(delete(EvoLooseLink))
    session.execute(delete(EvoCrossLink))
    session.commit()


def themes_to_label(session: Session) -> list[tuple[EvoGapTheme, str, list[str]]]:
    """Gap themes without a 9B label, with their topic's name and up to six statements (own text first)."""
    out = []
    themes = session.execute(select(EvoGapTheme, EvoTopic.name)
                             .join(EvoTopic, EvoGapTheme.topic_id == EvoTopic.id)).all()
    for theme, topic_name in themes:
        if (theme.detail or {}).get("label_model"):
            continue
        gaps = session.execute(select(EvoGapStatement)
                               .join(EvoGapThemeMember, EvoGapThemeMember.gap_id == EvoGapStatement.id)
                               .where(EvoGapThemeMember.theme_id == theme.id)).scalars().all()
        gaps = sorted(gaps, key=lambda g: g.origin != "own")[:6]
        out.append((theme, topic_name, [g.sentence[:400] for g in gaps]))
    return out


def save_theme_label(session: Session, theme_id: UUID, label: str, model: str) -> None:
    theme = session.get(EvoGapTheme, theme_id)
    theme.detail = {**(theme.detail or {}), "label_model": model, "terms_label": theme.label}
    theme.label = label
    session.commit()
