"""
Optional read-only copy of the research-evolution graph in Neo4j, for Cypher queries.

PostgreSQL stays the source of truth: every export wipes the evolution nodes
and rebuilds them, so the copy can never drift. Talks to Neo4j's HTTP API
(no driver dependency). Start Neo4j with the compose profile:

    docker compose -f docker/docker-compose.yml --profile graph up -d neo4j

Graph:
    (:Paper)-[:CITES {source}]->(:Paper)
    (:Paper)-[:IN_TOPIC {milestone, score, main_path, kind}]->(:Topic)
    (:Paper)-[:STATES_LIMITATION_OF {sentence, claims_fix}]->(:Paper)     strict links
    (:Paper)-[:LOOSELY_MATCHES {score, gap}]->(:Paper)                    loose links
    (:GapTheme {label, status, size})-[:OF_TOPIC]->(:Topic)
    (:Paper)-[:HAS_GAP_IN {statements}]->(:GapTheme)
"""
from __future__ import annotations

from collections import Counter

import httpx
from loguru import logger
from sqlalchemy import select

from athena.core.config_store import get_setting
from athena.core.models import (
    EvoCitation, EvoCitationContext, EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink, EvoPaper, EvoTopic,
    EvoTopicPaper,
)
from athena.database import evolution as db
from athena.database.db import SessionLocal

BATCH = 2000
LABELS = ["Paper", "Topic", "GapTheme"]


class Neo4j:
    def __init__(self, url: str | None = None, user: str | None = None, password: str | None = None,
                 database: str | None = None, http: httpx.Client | None = None):
        url = (url or get_setting("NEO4J_URL", "http://localhost:7474")).rstrip("/")
        database = database or get_setting("NEO4J_DATABASE", "neo4j")
        self.endpoint = f"{url}/db/{database}/tx/commit"
        auth = (user or get_setting("NEO4J_USER", "neo4j"), password or get_setting("NEO4J_PASSWORD", "athena_graph"))
        self.http = http or httpx.Client(timeout=300.0, auth=auth)

    def run(self, statement: str, **params) -> list[dict]:
        resp = self.http.post(self.endpoint, json={"statements": [{"statement": statement, "parameters": params}]})
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Neo4j: {body['errors'][0].get('message')}")
        result = body["results"][0]
        return [dict(zip(result["columns"], row["row"])) for row in result["data"]]

    def batched(self, statement: str, rows: list[dict]) -> None:
        for start in range(0, len(rows), BATCH):
            self.run(statement, rows=rows[start:start + BATCH])


def export(neo: Neo4j | None = None) -> dict:
    """Rebuild the Neo4j copy from PostgreSQL. Returns counts of what was written."""
    neo = neo or Neo4j()
    for label in LABELS:
        neo.run(f"MATCH (n:{label}) CALL {{ WITH n DETACH DELETE n }} IN TRANSACTIONS OF 10000 ROWS")
    for label, key in [("Paper", "id"), ("Topic", "slug"), ("GapTheme", "id")]:
        neo.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    counts: Counter = Counter()
    with SessionLocal() as session:
        topics = list(session.execute(select(EvoTopic)).scalars())
        neo.batched("UNWIND $rows AS r MERGE (t:Topic {slug: r.slug}) SET t.name = r.name, t.status = r.status",
                    [{"slug": t.slug, "name": t.name, "status": t.status} for t in topics])
        counts["topics"] = len(topics)

        in_topic = session.execute(select(EvoTopicPaper, EvoTopic.slug)
                                   .join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id)).all()
        paper_ids = {tp.paper_id for tp, _ in in_topic}
        papers = list(session.execute(select(EvoPaper).where(EvoPaper.id.in_(paper_ids))).scalars())
        neo.batched("UNWIND $rows AS r MERGE (p:Paper {id: r.id}) SET p += r.props",
                    [{"id": str(p.id), "props": {
                        "title": p.title, "year": p.year, "openalex_id": p.openalex_id, "arxiv_id": p.arxiv_id,
                        "doi": p.doi, "citations": max(p.cited_by_count or 0, p.s2_cited_by_count or 0),
                        "full_text": p.full_text_status}} for p in papers])
        counts["papers"] = len(papers)

        overrides = {}
        for topic in topics:
            for paper_id, o in db._overrides(session, topic.id).items():
                overrides[(topic.slug, paper_id)] = o.action
        neo.batched("""UNWIND $rows AS r MATCH (p:Paper {id: r.paper}), (t:Topic {slug: r.topic})
                       MERGE (p)-[e:IN_TOPIC]->(t) SET e += r.props""",
                    [{"paper": str(tp.paper_id), "topic": slug, "props": {
                        "milestone": db.effective_milestone(tp.is_milestone_auto, overrides.get((slug, tp.paper_id))),
                        "score": tp.milestone_score, "main_path": tp.on_main_path, "kind": tp.kind,
                        "in_degree": tp.in_degree}} for tp, slug in in_topic])
        counts["in_topic"] = len(in_topic)

        cites = session.execute(select(EvoCitation).where(EvoCitation.citing_id.in_(paper_ids),
                                                          EvoCitation.cited_id.in_(paper_ids))).scalars().all()
        neo.batched("""UNWIND $rows AS r MATCH (a:Paper {id: r.a}), (b:Paper {id: r.b})
                       MERGE (a)-[e:CITES]->(b) SET e.source = r.source""",
                    [{"a": str(c.citing_id), "b": str(c.cited_id), "source": c.source} for c in cites])
        counts["cites"] = len(cites)

        strict = session.execute(select(EvoCitationContext).where(
            EvoCitationContext.label.in_(db.LIMITATION_LABELS), EvoCitationContext.attributed.is_(True),
            EvoCitationContext.citing_id.in_(paper_ids), EvoCitationContext.cited_id.in_(paper_ids))).scalars().all()
        neo.batched("""UNWIND $rows AS r MATCH (a:Paper {id: r.a}), (b:Paper {id: r.b})
                       CREATE (a)-[:STATES_LIMITATION_OF {sentence: r.sentence, claims_fix: r.fix}]->(b)""",
                    [{"a": str(c.citing_id), "b": str(c.cited_id), "sentence": c.sentence,
                      "fix": c.label == "addresses_limitation"} for c in strict])
        counts["strict_links"] = len(strict)

        loose = session.execute(select(EvoLooseLink, EvoGapStatement)
                                .join(EvoGapStatement, EvoLooseLink.gap_id == EvoGapStatement.id)
                                .where(EvoLooseLink.score >= db.LOOSE_MIN_SCORE,
                                       EvoLooseLink.paper_id.in_(paper_ids),
                                       EvoGapStatement.paper_id.in_(paper_ids))).all()
        neo.batched("""UNWIND $rows AS r MATCH (a:Paper {id: r.a}), (b:Paper {id: r.b})
                       CREATE (a)-[:LOOSELY_MATCHES {score: r.score, gap: r.gap}]->(b)""",
                    [{"a": str(link.paper_id), "b": str(g.paper_id), "score": link.score, "gap": g.sentence}
                     for link, g in loose])
        counts["loose_links"] = len(loose)

        themes = session.execute(select(EvoGapTheme, EvoTopic.slug)
                                 .join(EvoTopic, EvoGapTheme.topic_id == EvoTopic.id)).all()
        neo.batched("""UNWIND $rows AS r MATCH (t:Topic {slug: r.topic})
                       MERGE (g:GapTheme {id: r.id}) SET g += r.props MERGE (g)-[:OF_TOPIC]->(t)""",
                    [{"id": str(th.id), "topic": slug, "props": {
                        "label": th.label, "status": th.status, "size": th.size, "first_year": th.first_year,
                        "last_year": th.last_year}} for th, slug in themes])
        has_gap = Counter((str(g.paper_id), str(m.theme_id)) for m, g in session.execute(
            select(EvoGapThemeMember, EvoGapStatement)
            .join(EvoGapStatement, EvoGapThemeMember.gap_id == EvoGapStatement.id)).all())
        neo.batched("""UNWIND $rows AS r MATCH (p:Paper {id: r.paper}), (g:GapTheme {id: r.theme})
                       MERGE (p)-[e:HAS_GAP_IN]->(g) SET e.statements = r.n""",
                    [{"paper": p, "theme": t, "n": n} for (p, t), n in has_gap.items()])
        counts["themes"] = len(themes)
    logger.info(f"Neo4j copy rebuilt: {dict(counts)}")
    return dict(counts)
