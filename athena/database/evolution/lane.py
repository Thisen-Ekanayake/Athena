"""
The model lane's queues (athena.evolution.model_lane): Tier 2 papers and their full text, chunks, citing
sentences, labels, abstracts and vectors.
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
    EvoChunk, EvoCitation, EvoCitationContext, EvoGapStatement, EvoLooseLink, EvoPaper, EvoSection, EvoTopic,
    EvoTopicPaper,
)
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.database.evolution.topics import LIMITATION_LABELS, _chunks, _overrides, _topic_rows, effective_milestone

if TYPE_CHECKING:
    from athena.evolution.fulltext import FullTextResult, KnownPaper, Tier2Paper


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


# Errors from parsing a paper's own PDF: trying again gives the same answer.
_PARSE_ERRORS = ("TEI:", "no body text")


def needs_full_text(paper: EvoPaper) -> bool:
    """Whether a Tier 2 paper should be fetched again.

    Never tried; or tried without a PDF and an arXiv ID has turned up since (a rebuild can bring one from
    Semantic Scholar; a download that timed out is retried too). A paper that failed with neither a PDF nor a
    Semantic Scholar ID (every paper of a map built without a key) is tried again once a rebuild gives it one.
    """
    last = (paper.extra or {}).get("full_text")
    if paper.full_text_status in ("available", "unavailable"):
        return last is None or paper.arxiv_id is not None
    if paper.full_text_status == "failed" and last and last.get("status") == "failed":
        error = str(last.get("error") or "")
        return not error.startswith(_PARSE_ERRORS) and bool(paper.s2_paper_id or paper.arxiv_id)
    return False


def tier2_papers(session: Session, ids: set[UUID], reparse: bool = False) -> list["Tier2Paper"]:
    """The papers in ``ids`` still needing full text (all of them with ``reparse``), with their known refs."""
    from athena.evolution.fulltext import Tier2Paper  # fulltext needs igraph, which the API image lacks
    papers = list(session.execute(select(EvoPaper).where(EvoPaper.id.in_(ids))).scalars())
    if not reparse:
        papers = [p for p in papers if needs_full_text(p)]
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
        elif result.status == "s2_contexts" and paper.full_text_status == "failed":
            # It failed before for want of a Semantic Scholar ID: it has citing sentences now, not a broken PDF.
            paper.full_text_status = "available" if (paper.arxiv_id or paper.oa_pdf_url) else "unavailable"
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


def cited_by(session: Session, paper_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    """{paper: papers citing it}, for flagging loose links that coincide with a citation."""
    out: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id)
                                         .where(EvoCitation.cited_id.in_(paper_ids))):
        out[cited].add(citing)
    return out


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
    """Mark every chunk, gap statement and abstract as not embedded, and drop the loose links.

    For a switch of embedding model: the next GPU lane embeds everything again and rebuilds the themes.
    """
    session.execute(update(EvoChunk).values(embedded_at=None))
    session.execute(update(EvoGapStatement).values(embedded_at=None, loose_checked_at=None))
    session.execute(update(EvoPaper).values(abstract_embedded_at=None))
    session.execute(delete(EvoLooseLink))
    session.commit()
