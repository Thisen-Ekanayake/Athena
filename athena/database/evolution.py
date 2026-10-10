"""
Database reads and writes for the research evolution feature.

Kept free of the graph libraries (igraph) so the API image, which installs
only requirements.api.txt, can import it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from athena.core.models import (
    EvoChunk, EvoCitation, EvoCitationContext, EvoMainPathEdge, EvoMilestoneOverride, EvoPaper, EvoSection,
    EvoTopic, EvoTopicPaper,
)
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig

if TYPE_CHECKING:
    from athena.evolution.corpus import Corpus
    from athena.evolution.fulltext import FullTextResult, KnownPaper, Tier2Paper
    from athena.evolution.milestones import TopicScores

OVERRIDE_ACTIONS = {"pin", "unpin", "reset"}
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
                 config: dict) -> None:
    values = {"slug": slug, "name": name, "aliases": aliases, "description": description, "seeds": seeds,
              "config": config}
    with SessionLocal() as session:
        stmt = insert(EvoTopic).values(id=uuid4(), status="pending", **values)
        stmt = stmt.on_conflict_do_update(index_elements=["slug"], set_=values)
        session.execute(stmt)
        session.commit()


def get_topic(session: Session, slug: str) -> EvoTopic | None:
    return session.execute(select(EvoTopic).where(EvoTopic.slug == slug)).scalar_one_or_none()


def set_topic_status(slug: str, status: str, detail: str | None = None) -> None:
    with SessionLocal() as session:
        topic = get_topic(session, slug)
        if topic is None:
            return
        topic.status = status
        topic.status_detail = detail
        if status == "ready":
            topic.built_at = datetime.now(timezone.utc)
        session.commit()


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


def _node(tp: EvoTopicPaper, p: EvoPaper, override: EvoMilestoneOverride | None) -> dict:
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
        "named_method": tp.named_method,
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
        "url": f"https://arxiv.org/abs/{p.arxiv_id}" if p.arxiv_id else (
            f"https://doi.org/{p.doi}" if p.doi else f"https://openalex.org/{p.openalex_id}"),
    }


def topic_graph(session: Session, topic: EvoTopic, limit: int = 250) -> dict:
    """Milestones, main-path papers and seeds, then the highest-scoring papers up to ``limit``."""
    overrides = _overrides(session, topic.id)
    nodes = [_node(tp, p, overrides.get(p.id)) for tp, p in _topic_rows(session, topic.id)]
    total = len(nodes)
    nodes.sort(key=lambda n: (n["is_milestone"] or n["on_main_path"] or n["role"] == "seed",
                              n["milestone_score"]), reverse=True)
    nodes = nodes[:max(limit, sum(1 for n in nodes if n["is_milestone"] or n["on_main_path"]))]
    shown = {UUID(n["id"]) for n in nodes}

    main = {(r.citing_id, r.cited_id) for r in session.execute(
        select(EvoMainPathEdge).where(EvoMainPathEdge.topic_id == topic.id)).scalars()}
    edges = [
        {"source": str(c), "target": str(d), "main_path": (c, d) in main}
        for c, d in session.execute(
            select(EvoCitation.citing_id, EvoCitation.cited_id)
            .where(EvoCitation.citing_id.in_(shown), EvoCitation.cited_id.in_(shown))
        ).all()
    ]
    years = [n["year"] for n in nodes if n["year"]]
    return {
        "topic": topic_summary(topic),
        "nodes": nodes,
        "edges": edges,
        "total_papers": total,
        "year_range": [min(years), max(years)] if years else None,
    }


def topic_timeline(session: Session, topic: EvoTopic, notable: int = 40) -> dict:
    """Milestones by year, plus notable papers whose full text is not openly available."""
    overrides = _overrides(session, topic.id)
    nodes = [_node(tp, p, overrides.get(p.id)) for tp, p in _topic_rows(session, topic.id)]
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

    def neighbours(ids: list[UUID]) -> list[dict]:
        found = [_node(*in_topic[i], overrides.get(i)) for i in ids if i in in_topic]
        return sorted(found, key=lambda n: n["milestone_score"], reverse=True)[:10]

    refs = [r for (r,) in session.execute(select(EvoCitation.cited_id).where(EvoCitation.citing_id == p.id))]
    citers = [c for (c,) in session.execute(select(EvoCitation.citing_id).where(EvoCitation.cited_id == p.id))]
    return _node(tp, p, overrides.get(p.id)) | {
        "abstract": p.abstract,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "openalex_year": p.openalex_year,
        "merged_ids": p.merged_ids or [],
        "builds_on": neighbours(refs),
        "built_upon_by": neighbours(citers),
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
        query = query.where(EvoPaper.full_text_status.in_(["available", "unavailable"]),
                            or_(EvoPaper.extra.is_(None), ~EvoPaper.extra.has_key("full_text")))
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
            session.execute(insert(EvoCitationContext).values(chunk)
                            .on_conflict_do_nothing(constraint="uq_evo_citation_context"))

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
