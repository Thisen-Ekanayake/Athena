"""
Idea and novelty check (ROADMAP E2): an idea or abstract against every built map.

1. The closest papers: the idea against every map paper's title and abstract
   (Qdrant's ``paper_abstracts``).
2. The gaps it touches: the idea against every gap statement
   (``gap_statements``), grouped by the gap theme each statement belongs to,
   with the theme's status: persisting and new themes are still open,
   addressed ones have a claimed fix, quiet ones are no longer stated.
3. Optionally, a short verdict from the chat model: the closest prior work,
   and what would be new.

Both searches embed the idea as a query with its own instruction, in the
evolution collections' space (``athena.evolution.search.embed_query``).
"""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

PAPER_INSTRUCT = "Given a research idea, retrieve titles and abstracts of the most similar earlier papers"
GAP_INSTRUCT = "Given a research idea, retrieve statements of research gaps or limitations that the idea would address"
PAPER_HITS = 15
GAP_HITS = 40
# Floors set by eye on ten dev ideas (recent feed abstracts, none in a map), checked on ten test ideas, and the
# theme floor confirmed on ten more. Papers: unrelated ideas (quantum classifiers, weather forecasting) topped
# out near 0.60, related prior work started around 0.62. Gap statements are short and noisier: on the test
# ideas, themes whose best statement scored 0.50-0.55 were mostly unrelated (5 of 17 shown were relevant, all
# at 0.55 or above), so a theme needs one statement at THEME_MIN_SCORE; weaker statements still count as hits.
PAPER_MIN_SCORE = 0.6
GAP_MIN_SCORE = 0.5
THEME_MIN_SCORE = 0.55
MAX_THEMES = 8
OPEN = {"persisting", "new"}

VERDICT_SYSTEM = "You compare a research idea with published work. Reply with JSON only."
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"closest": {"type": "string", "maxLength": 600}, "new": {"type": "string", "maxLength": 600},
                   "gaps": {"type": "string", "maxLength": 450}},
    "required": ["closest", "new", "gaps"], "additionalProperties": False,
}


class IdeaCheckUnavailable(RuntimeError):
    """No embedding endpoint answered, or the collections are missing."""


def _search(collection: str, vector, limit: int, floor: float) -> list[tuple[UUID, float]]:
    from athena.evolution import vectors
    qdrant = vectors.client()
    if not qdrant.collection_exists(collection):
        return []
    hits = qdrant.query_points(collection, query=vector.tolist(), limit=limit).points
    return [(UUID(str(h.id)), float(h.score)) for h in hits if h.score >= floor]


def closest_papers(session: Session, hits: list[tuple[UUID, float]]) -> list[dict]:
    from athena.core.models import EvoPaper
    from athena.database import evolution as db
    if not hits:
        return []
    ids = [pid for pid, _ in hits]
    papers = {p.id: p for p in session.execute(select(EvoPaper).where(EvoPaper.id.in_(ids))).scalars()}
    membership = db.map_membership(session, ids)
    out = []
    for pid, score in hits:
        p = papers.get(pid)
        if p is None or pid not in membership:
            continue  # not in a built map any more
        out.append({"id": str(pid), "title": p.title, "year": p.year, "authors": (p.authors or [])[:3],
                    "abstract": (p.abstract or "")[:600], "url": db._paper_url(p), "score": round(score, 3),
                    "maps": [{"topic": m["topic"], "topic_name": m["topic_name"], "milestone": m["milestone"]}
                             for m in membership[pid]]})
    return out


def touched_themes(session: Session, hits: list[tuple[UUID, float]]) -> tuple[list[dict], list[dict]]:
    """Gap themes the idea's nearest gap statements belong to, best match first, and statements in no theme."""
    from athena.core.models import (
        EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink, EvoPaper, EvoTopic, EvoTopicPaper,
    )
    from athena.database import evolution as db
    if not hits:
        return [], []
    score = dict(hits)
    statements = {g.id: g for g in session.execute(select(EvoGapStatement).where(
        EvoGapStatement.id.in_(list(score)))).scalars()}
    themed: dict[UUID, list[UUID]] = defaultdict(list)
    themes: dict[UUID, tuple] = {}
    for gap_id, theme, topic in session.execute(
            select(EvoGapThemeMember.gap_id, EvoGapTheme, EvoTopic)
            .join(EvoGapTheme, EvoGapThemeMember.theme_id == EvoGapTheme.id)
            .join(EvoTopic, EvoGapTheme.topic_id == EvoTopic.id)
            .where(EvoGapThemeMember.gap_id.in_(list(score)))):
        themed[theme.id].append(gap_id)
        themes[theme.id] = (theme, topic)
    paper_ids = {g.paper_id for g in statements.values()} | {g.source_paper_id for g in statements.values()}
    for theme, _ in themes.values():
        paper_ids |= {UUID(p) for p in (theme.detail or {}).get("fixed_by", [])}
    titles = {pid: (title, year) for pid, title, year in session.execute(
        select(EvoPaper.id, EvoPaper.title, EvoPaper.year).where(EvoPaper.id.in_(list(paper_ids))))}

    def paper(pid) -> dict | None:
        if pid not in titles:
            return None
        title, year = titles[pid]
        return {"id": str(pid), "title": title, "year": year}

    out = []
    for theme_id, gap_ids in themed.items():
        theme, topic = themes[theme_id]
        best = max(gap_ids, key=lambda g: score[g])
        if score[best] < THEME_MIN_SCORE:
            continue
        g = statements[best]
        # Later papers whose text matches the theme's statements: candidates for having addressed it.
        members = [m for (m,) in session.execute(select(EvoGapThemeMember.gap_id).where(
            EvoGapThemeMember.theme_id == theme_id))]
        candidates: dict[UUID, float] = {}
        for link, kind in session.execute(
                select(EvoLooseLink, EvoTopicPaper.kind)
                .join(EvoTopicPaper, (EvoTopicPaper.paper_id == EvoLooseLink.paper_id)
                      & (EvoTopicPaper.topic_id == topic.id))
                .where(EvoLooseLink.gap_id.in_(members), EvoLooseLink.score >= db.LOOSE_MIN_SCORE)):
            if kind == "method":
                candidates[link.paper_id] = max(link.score, candidates.get(link.paper_id, 0.0))
        cand_titles = dict(session.execute(select(EvoPaper.id, EvoPaper.title).where(
            EvoPaper.id.in_(list(candidates)))).all()) if candidates else {}
        out.append({
            "id": str(theme_id), "label": theme.label, "status": theme.status, "open": theme.status in OPEN,
            "topic": topic.slug, "topic_name": topic.name, "size": theme.size,
            "first_year": theme.first_year, "last_year": theme.last_year,
            "score": round(score[best], 3), "hits": len(gap_ids),
            "example": {"sentence": g.sentence, "paper": paper(g.paper_id),
                        "stated_by": paper(g.source_paper_id) if g.origin == "citing" else None},
            "fixed_by": [x for x in (paper(UUID(p)) for p in (theme.detail or {}).get("fixed_by", [])) if x][:5],
            "maybe_addressed_by": [{"id": str(pid), "title": cand_titles.get(pid), "score": round(s, 3)}
                                   for pid, s in sorted(candidates.items(), key=lambda kv: -kv[1])[:3]],
        })
    out.sort(key=lambda t: -t["score"])
    in_theme = {g for ids in themed.values() for g in ids}
    loose = [{"sentence": statements[gid].sentence, "score": round(s, 3), "paper": paper(statements[gid].paper_id)}
             for gid, s in sorted(hits, key=lambda kv: -kv[1]) if gid in statements and gid not in in_theme][:5]
    return out[:MAX_THEMES], loose


def verdict_schema(with_gaps: bool) -> dict:
    keys = ["closest", "new", "gaps"] if with_gaps else ["closest", "new"]
    return {"type": "object", "properties": {k: VERDICT_SCHEMA["properties"][k] for k in keys},
            "required": keys, "additionalProperties": False}


def verdict_prompt(idea: str, papers: list[dict], themes: list[dict]) -> str:
    """Asks about gaps only when some matched: with none listed, the model made one up from the idea itself."""
    listed = "\n".join(f"[{i}] {p['title']} ({p['year']}): {p['abstract'][:400]}" for i, p in enumerate(papers[:6], 1))
    parts = [f"Research idea:\n{idea[:3000]}", f"The most similar published papers:\n{listed or 'none found'}"]
    asks = ["closest: which listed papers come closest to the idea, and how (say so if none is close);",
            "new: what in the idea is not covered by the listed papers (say so plainly if everything is);"]
    if themes:
        gaps = "\n".join(f"- {t['label']} ({t['topic_name']}; {'still open' if t['open'] else t['status']}): "
                         f"\"{t['example']['sentence'][:200]}\"" for t in themes[:5])
        parts.append(f"Research gaps that papers in these fields state, which the idea may touch:\n{gaps}")
        asks.append("gaps: which of the listed gaps the idea would address; say so if none.")
    keys = ", ".join(f'"{k.split(":")[0]}": "..."' for k in asks)
    return ("\n\n".join(parts) + f"\n\nAnswer in {len(asks)} short parts, each at most 60 words, citing papers by "
            "their [number]:\n" + "\n".join(asks) + "\nUse only the information above.\n" + f"Return {{{keys}}}.")


def check_idea(session: Session, idea: str, verdict: bool = True, user_id=None) -> dict:
    from athena.core import llm
    from athena.evolution import vectors
    from athena.evolution.search import embed_query

    paper_vec = embed_query(idea, PAPER_INSTRUCT, timeout=30.0)
    gap_vec = embed_query(idea, GAP_INSTRUCT, timeout=30.0)
    if paper_vec is None or gap_vec is None:
        raise IdeaCheckUnavailable("The embedding model did not answer; start the model server and try again.")
    papers = closest_papers(session, _search(vectors.ABSTRACT_COLLECTION, paper_vec, PAPER_HITS, PAPER_MIN_SCORE))
    themes, unthemed = touched_themes(session, _search(vectors.GAP_COLLECTION, gap_vec, GAP_HITS, GAP_MIN_SCORE))
    result = {"papers": papers, "themes": themes, "unthemed_gaps": unthemed, "verdict": None, "usage": None}
    if verdict and (papers or themes):
        try:
            answer, usage = llm.chat_json(verdict_prompt(idea, papers, themes), verdict_schema(bool(themes)),
                                          "idea_verdict", system=VERDICT_SYSTEM, max_tokens=500,
                                          feature="idea_check", user_id=user_id)
            result["verdict"] = answer
            result["usage"] = usage
        except Exception as exc:  # the search results still stand without the model's reading of them
            result["verdict_error"] = str(exc)[:300]
    return result
