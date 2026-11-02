"""
The model lane (the "GPU lane"): one model on the 8 GB card at a time.

Qwen3-Embedding-8B (4.7 GB) and Qwen3.5-9B (5.7 GB) do not fit together, so
a lane run asks the 9B to label every pending citing sentence and gap
candidate, then the embedder for every chunk and gap statement without a
vector and searches loose links, and finally rebuilds the gap themes on the
CPU. Both models are served by llama-server in router mode
(``config/llama-router.ini``, ``--models-max 1``), which swaps them on demand;
asking for them in phases keeps the swaps to the phase boundaries. It runs on
the single-concurrency Celery ``evolution`` queue so two lanes never compete
for the card.

Endpoints and model names come from athena.core.llm; EVOLUTION_CHAT_URL,
EVOLUTION_EMBED_URL and EVOLUTION_*_MODEL_NAME override them for the lane.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from uuid import UUID

import httpx
import numpy as np
from loguru import logger

from sqlalchemy import select

from athena.core import llm, usage
from athena.model_server import activity, lane
from athena.core.config_store import get_setting
from athena.core.models import EvoTopic
from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution import progress, vectors
from athena.evolution.classify import Classifier, auth_headers, chat_url, embed_model_name, embed_url, is_local
from athena.evolution.gaps import build_themes, keep_names

# Phase 0: throughput is the same with one slot as with eight, and every input must fit one ubatch.
MAX_CHUNK_TOKENS = llm.EMBED_MAX_TOKENS
EXTERNAL_MAX_WORDS = 600  # without a tokenizer endpoint, a word cap well inside common 8k contexts
EMBED_BATCH = 8
FETCH = 256
# Loose links (Phase 3): a gap statement against later papers' abstract, introduction and method chunks.
# Phase 0 measured recall@10 of 0.73 for this instruction. The API applies the shown cutoff; the floor
# only keeps the table small.
LOOSE_INSTRUCT = "Given a limitation stated in a research paper, retrieve passages from later papers that address it"
LOOSE_SECTIONS = ["abstract", "intro", "method"]
LOOSE_PER_GAP = 3
LOOSE_FLOOR = 0.3


class EndpointUnavailable(RuntimeError):
    """The model server does not answer (llama-server not started, or the URL is wrong)."""


@contextmanager
def endpoint(url: str):
    """Check a llama.cpp endpoint answers before a lane phase; hosted endpoints are taken on trust."""
    if is_local():
        try:
            healthy = httpx.get(f"{url}/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            healthy = False
        if not healthy:
            raise EndpointUnavailable(f"No model server at {url}. Start it with: llama-server --models-preset "
                                      "config/llama-router.ini --models-max 1 --port 8080")
    yield


def embed_server():
    url = embed_url()
    return url, endpoint(url)


def chat_server():
    url = chat_url()
    return url, endpoint(url)


# ── embedding ──────────────────────────────────────────────────────────


def _fit(http: httpx.Client, url: str, text: str) -> tuple[str, bool]:
    """Trim ``text`` until it fits MAX_CHUNK_TOKENS, counted by the server's tokenizer.

    External endpoints have no /tokenize, so there the text is cut at a word count instead.
    """
    if not is_local():
        words = text.split()
        return " ".join(words[:EXTERNAL_MAX_WORDS]), len(words) > EXTERNAL_MAX_WORDS
    model = embed_model_name()  # the router needs it to pick the tokenizer
    return llm.fit(text, MAX_CHUNK_TOKENS, lambda t: _count_tokens(http, url, model, t))


TOKENIZE_TRIES = 5


def _count_tokens(http: httpx.Client, url: str, model: str, text: str) -> int:
    """Tokens in ``text`` by the embedder's tokenizer. In router mode /tokenize loads the embedder, so it takes the
    embedder's turn on the GPU first; a router that answers with an error while it swaps models is asked again
    (2026-11-02: a lane run died on the KeyError)."""
    lane.yield_to_chat(who="map_embed", model=model)
    body: dict = {}
    for attempt in range(TOKENIZE_TRIES):
        body = http.post(f"{url}/tokenize", json={"content": text, "model": model}).json()
        if "tokens" in body:
            return len(body["tokens"])
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"The model server did not tokenize the text: {str(body)[:200]}")


def _embed(http: httpx.Client, url: str, texts: list[str]) -> np.ndarray:
    body: dict = {"input": texts, "model": embed_model_name()}
    lane.yield_to_chat(who="map_embed", model=body["model"])  # between batches: chats first, then the GPU's turns
    dimensions = get_setting("EVOLUTION_EMBED_DIMENSIONS") or get_setting("EMBED_DIMENSIONS")
    if dimensions:  # OpenAI's text-embedding-3 models shorten vectors themselves
        body["dimensions"] = int(dimensions)
    with activity.track("map_embed", body["model"], kind="embed") as call:
        resp = http.post(f"{url}/v1/embeddings", json=body)
        resp.raise_for_status()
        call.tokens(usage.tokens_of(resp.json().get("usage"))[0])
    usage.add("map_embed", body["model"], usage.tokens_of(resp.json().get("usage"))[0], kind="embed")
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    raw = np.asarray([d["embedding"] for d in data])
    if raw.shape[1] < vectors.DIM:
        raise ValueError(f"The embedding model returns {raw.shape[1]} dimensions; the collections need at least "
                         f"{vectors.DIM}. Use a model with more, or rebuild the collections for this one.")
    return vectors.truncate(raw)


def _embed_chunks(http: httpx.Client, url: str, session, limit: int | None, papers: set | None = None) -> dict:
    done = trimmed = 0
    start = time.time()
    while limit is None or done < limit:
        _step_aside()
        rows = db.pending_chunks(session, FETCH if limit is None else min(FETCH, limit - done), papers)
        if not rows:
            break
        topics = db.paper_topics(session, list({c.paper_id for c, _, _ in rows}))
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i:i + EMBED_BATCH]
            texts = []
            for chunk, paper, section in batch:
                # Only the title and heading are prefixed: author names would make papers look alike.
                text, cut = _fit(http, url, f"{paper.title}\n{section.heading}\n{chunk.text}")
                texts.append(text)
                trimmed += cut
            vecs = _embed(http, url, texts)
            vectors.upsert([(chunk.id, vec, {"paper_id": str(paper.id), "topic_ids": topics.get(paper.id, []),
                                             "year": paper.year, "section_type": chunk.section_type,
                                             "position": chunk.position})
                            for (chunk, paper, _), vec in zip(batch, vecs)])
            db.mark_embedded(session, [c.id for c, _, _ in batch])
            done += len(batch)
        logger.info(f"Embedded {done} chunks ({done / max(time.time() - start, 1e-6):.1f}/s, {trimmed} trimmed)")
    return {"chunks_embedded": done, "chunks_trimmed": trimmed}


def _embed_gaps(http: httpx.Client, url: str, session, papers: set | None = None) -> int:
    """Gap statements as documents: the sentence alone, so themes group by gap rather than by paper."""
    vectors.ensure_collection(name=vectors.GAP_COLLECTION)
    done = 0
    while rows := db.pending_gap_vectors(session, FETCH, papers):
        _step_aside()
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i:i + EMBED_BATCH]
            vecs = _embed(http, url, [_fit(http, url, g.sentence)[0] for g, _ in batch])
            vectors.upsert([(g.id, vec, {"paper_id": str(g.paper_id), "origin": g.origin, "year": year})
                            for (g, year), vec in zip(batch, vecs)], name=vectors.GAP_COLLECTION)
            db.mark_gaps(session, [g.id for g, _ in batch], "embedded_at")
            done += len(batch)
    logger.info(f"Embedded {done} gap statements")
    return done


def _embed_abstracts(http: httpx.Client, url: str, session, scope: set | None = None) -> int:
    """Tier 1: every topic paper's title and abstract (``scope``: these papers'), for topic search."""
    vectors.ensure_collection(name=vectors.ABSTRACT_COLLECTION)
    done = 0
    while papers := db.pending_abstracts(session, FETCH, scope):
        _step_aside()
        for i in range(0, len(papers), EMBED_BATCH):
            batch = papers[i:i + EMBED_BATCH]
            vecs = _embed(http, url, [_fit(http, url, f"{p.title}\n{p.abstract or ''}")[0] for p in batch])
            vectors.upsert([(p.id, vec, {"paper_id": str(p.id), "year": p.year}) for p, vec in zip(batch, vecs)],
                           name=vectors.ABSTRACT_COLLECTION)
            db.mark_abstracts(session, [p.id for p in batch])
            done += len(batch)
    logger.info(f"Embedded {done} abstracts")
    return done


def _loose_links(http: httpx.Client, url: str, session, papers: set | None = None) -> int:
    """For each gap statement, the later papers whose abstract, introduction or method matches it best."""
    found = 0
    while rows := db.pending_loose(session, FETCH, papers):
        _step_aside()
        topics = db.paper_topics(session, list({g.paper_id for g, _ in rows}))
        citers = db.cited_by(session, list({g.paper_id for g, _ in rows}))
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i:i + EMBED_BATCH]
            queries = [f"Instruct: {LOOSE_INSTRUCT}\nQuery: {_fit(http, url, g.sentence)[0]}" for g, _ in batch]
            for (g, year), vec in zip(batch, _embed(http, url, queries)):
                if not topics.get(g.paper_id):
                    db.save_loose_links(session, g.id, [])
                    continue
                hits = vectors.later_chunks(vec, year, topics[g.paper_id], [str(g.paper_id), str(g.source_paper_id)],
                                            LOOSE_SECTIONS, limit=20)
                best: dict[str, object] = {}
                for hit in hits:  # nearest first, so the first chunk seen per paper is its best
                    best.setdefault(hit.payload["paper_id"], hit)
                links = [{"paper_id": UUID(pid), "chunk_id": UUID(str(hit.id)), "score": float(hit.score),
                          "cites": UUID(pid) in citers.get(g.paper_id, set())}
                         for pid, hit in list(best.items())[:LOOSE_PER_GAP] if hit.score >= LOOSE_FLOOR]
                db.save_loose_links(session, g.id, links)
                found += len(links)
            db.mark_gaps(session, [g.id for g, _ in batch], "loose_checked_at")
    logger.info(f"Found {found} loose links")
    return found


def embed_abstracts() -> int:
    """Tier 1 only: abstracts without a vector (a new search-built topic's), with no chunks, gaps or links."""
    url, server = embed_server()
    llm.check_embed_space("evolution", embed_model_name())
    with server, httpx.Client(timeout=600.0, headers=auth_headers(url)) as http, SessionLocal() as session:
        return _embed_abstracts(http, url, session)


def embed_pending(limit: int | None = None, scope: dict | None = None) -> dict:
    """Embed chunks and gap statements that have no vector yet, search loose links, then embed abstracts; ``scope``
    (``db.topic_scope``): one map's only."""
    vectors.ensure_collection()
    url, server = embed_server()
    llm.check_embed_space("evolution", embed_model_name())
    papers = scope["papers"] if scope else None
    with server, httpx.Client(timeout=600.0, headers=auth_headers(url)) as http, SessionLocal() as session:
        summary = _embed_chunks(http, url, session, limit, papers)
        if limit is None:
            summary["gaps_embedded"] = _embed_gaps(http, url, session, papers)
            summary["loose_links"] = _loose_links(http, url, session, papers)
            summary["abstracts_embedded"] = _embed_abstracts(http, url, session, papers)
    return summary


# ── classification ─────────────────────────────────────────────────────


def classify_pending(limit: int | None = None, scope: dict | None = None) -> dict:
    """Label cue-bearing citing sentences whose cited paper is in some topic's Tier 2, then gap candidates;
    ``scope`` (``db.topic_scope``): one map's only."""
    url, server = chat_server()
    labelled = strict = gaps = candidates = rechecked = confirmed = 0
    with server, SessionLocal() as session:
        clf = Classifier(base_url=url, wait={})  # each call waits for chats and the 9B's turn
        cited_ids = scope["tier2"] if scope else db.all_tier2_ids(session)
        if clf.local and scope is None:
            # Strict links labelled before the thinking confirmation existed: confirm them now.
            while rows := db.unconfirmed_strict(session, clf.model_tag, 32):
                _step_aside()
                out = [{"id": ctx.id, "label": ctx.label, "model": clf.model_tag,
                        "attributed": clf.attribution(citing_title, cited_title, ctx.sentence, ctx.marked,
                                                      think=True)} for ctx, citing_title, cited_title in rows]
                db.save_labels(session, out)
                confirmed += sum(bool(o["attributed"]) for o in out)
                rechecked += len(out)
                logger.info(f"Rechecked {rechecked} strict links with thinking, {confirmed} confirmed")
        slug = (scope or {}).get("slug")
        progress.stage(slug, "labelling", db.count_pending_contexts(session, cited_ids) if slug else None)
        start = time.time()
        while limit is None or labelled < limit:
            _step_aside()
            rows = db.pending_contexts(session, cited_ids, 64 if limit is None else min(64, limit - labelled))
            if not rows:
                break
            out = []
            for ctx, citing_title, cited_title in rows:
                v = clf.classify(citing_title, cited_title, ctx.sentence, ctx.marked)
                # A failed answer is stored as "unknown" so it is not retried forever.
                out.append({"id": ctx.id, "label": v.label or "unknown", "attributed": v.attributed,
                            "model": clf.model_tag})
                strict += v.strict
            db.save_labels(session, out)
            labelled += len(out)
            progress.advance(slug, len(out))
            logger.info(f"Labelled {labelled} citing sentences, {strict} strict "
                        f"({labelled / max(time.time() - start, 1e-6):.1f}/s)")
        papers = scope["papers"] if scope else None
        progress.stage(slug, "gaps")
        while limit is None and (rows := db.pending_gap_candidates(session, 64, papers)):
            _step_aside()
            out = []
            for gap, title in rows:
                label = clf.is_gap(title, gap.section_type, gap.sentence) or "unknown"
                out.append({"id": gap.id, "label": label, "model": clf.model})
                gaps += label == "gap"
            db.save_gap_labels(session, out)
            candidates += len(out)
            progress.advance(slug, len(out))
            logger.info(f"Labelled {candidates} gap candidates, {gaps} gaps")
    return {"strict_rechecked": rechecked, "strict_confirmed": confirmed, "contexts_labelled": labelled,
            "strict_links": strict, "gap_candidates_labelled": candidates, "gaps": gaps}


def _ready_topics(session, slug: str | None = None) -> list[EvoTopic]:
    q = select(EvoTopic).where(EvoTopic.status == "ready")
    if slug is not None:
        q = select(EvoTopic).where(EvoTopic.slug == slug)
    return list(session.execute(q).scalars())


def build_all_themes(slug: str | None = None) -> dict:
    """Gap themes for every built topic (or one), from the gap statements' vectors. CPU only."""
    out = {}
    with SessionLocal() as session:
        for topic in _ready_topics(session, slug):
            rows = db.topic_gap_rows(session, topic)
            vecs = vectors.vectors_for([r["id"] for r in rows]) if rows else {}
            rows = [r for r in rows if r["id"] in vecs]
            themes = build_themes(rows, np.asarray([vecs[r["id"]] for r in rows])) if rows else []
            kept = keep_names(themes, db.named_themes(session, topic.id))  # unchanged themes keep their 9B name
            db.save_themes(topic.id, themes)
            out[topic.slug] = {"gap_statements": len(rows), "themes": len(themes), "names_kept": kept,
                               "persisting": sum(t["status"] == "persisting" for t in themes)}
    logger.info(f"Gap themes: {out}")
    return out


def label_themes(slug: str | None = None) -> int:
    """Short 9B names for gap themes (one topic's, given one); a theme keeps its TF-IDF label when the answer is
    unusable."""
    url, server = chat_server()
    done = 0
    with SessionLocal() as session:
        topic_id = None
        if slug is not None:
            topic = db.get_topic(session, slug)
            if topic is None:
                return 0
            topic_id = topic.id
        pending = db.themes_to_label(session, topic_id)
        if not pending:
            return 0
        progress.stage(slug, "naming", len(pending))
        with server:
            clf = Classifier(base_url=url, wait={})
            for theme, topic_name, sentences in pending:
                _step_aside()
                label = clf.theme_label(topic_name, sentences)
                if label:
                    db.save_theme_label(session, theme.id, label, clf.model)
                    done += 1
                progress.advance(slug)
    logger.info(f"Labelled {done} gap themes")
    return done


# ── the lane ───────────────────────────────────────────────────────────


class StepAside(RuntimeError):
    """Backlog lane work stops because other work waits for the evolution worker; its task queues itself again
    behind that work, and what it labelled so far is kept."""


EVOLUTION_QUEUE = "evolution"  # the Celery queue (a Redis list) the single evolution worker serves


def _step_aside() -> None:
    """Between batches of backlog work: raise ``StepAside`` when other work waits on the evolution queue (a map
    someone is building, a full-text request, a proposal), so it does not wait hours behind maps nobody asked about.
    Work someone asked for never steps aside, and backlog runs never step aside for each other (each would see the
    other waiting, and they would swap places forever)."""
    from athena.model_server import turns
    if turns.priority_of("map_build") != turns.BACKLOG:
        return
    try:
        from athena.core.redis_client import get_redis
        waiting = [m for m in get_redis().lrange(EVOLUTION_QUEUE, 0, -1) if not _is_backlog(m)]
    except Exception:
        return
    if waiting:
        raise StepAside(f"{len(waiting)} task(s) wait for the evolution worker")


def backlog_queued() -> bool:
    """Whether a backlog lane run waits on the evolution queue."""
    try:
        from athena.core.redis_client import get_redis
        return any(_is_backlog(m) for m in get_redis().lrange(EVOLUTION_QUEUE, 0, -1))
    except Exception:
        return False


def _is_backlog(message) -> bool:
    """Whether a queued Celery message is a backlog lane run: ``run_gpu_lane`` or ``refresh_gpu_lane`` for no map
    in particular (an old chain's ``refresh_gpu_lane`` with no map is one too). Anything unreadable counts as other
    work."""
    import base64
    import json
    try:
        m = json.loads(message)
        task = m["headers"]["task"].rsplit(".", 1)[-1]
        body = m["body"]
        if m.get("properties", {}).get("body_encoding") == "base64":
            body = base64.b64decode(body)
        args, kwargs = json.loads(body)[:2]
    except Exception:
        return False
    if task == "run_gpu_lane":
        return (args[2] if len(args) > 2 else kwargs.get("slug")) is None
    if task == "refresh_gpu_lane":
        return (args[0] if args else kwargs.get("slug")) is None
    return False


def _run_scope(embed: bool, classify: bool, slug: str | None) -> dict:
    """The lane for one map (``slug``), or for whatever belongs to no map in particular (None)."""
    summary = {}
    scope = None
    if slug is not None:
        with SessionLocal() as session:
            topic = db.get_topic(session, slug)
            if topic is None:
                return {}
            scope = db.topic_scope(session, topic) | {"slug": slug}
    if classify:
        summary |= classify_pending(scope=scope)
    with SessionLocal() as session:
        summary["citing_gaps"] = db.sync_citing_gaps(session)
    if embed:
        progress.stage(slug, "embedding")
        summary |= embed_pending(scope=scope)
        progress.stage(slug, "themes")
        summary["themes"] = build_all_themes(slug)
        if classify:
            summary["theme_labels"] = label_themes(slug)
    progress.stage(slug, "done")
    return summary


def backlog_order() -> list[str]:
    """Ready maps with sentences left to label, fewest first: the shortest job first finishes each map soonest
    (a map's gaps show only once its themes are rebuilt, so sharing time between maps would only delay them all)."""
    with SessionLocal() as session:
        pending = []
        for topic in _ready_topics(session):
            left = db.count_pending_contexts(session, db.topic_scope(session, topic)["tier2"])
            if left:
                pending.append((left, topic.slug))
    return [slug for _, slug in sorted(pending)]


def run_lane(embed: bool = True, classify: bool = True, slug: str | None = None) -> dict:
    """Everything pending, one model at a time: the 9B, the embedder, themes on the CPU, then the 9B names them.

    With ``slug``, only that map's work (someone waits for its gaps; the rest is left for a backlog run). Without,
    the backlog: maps one at a time, fewest sentences left first (``backlog_order``), then whatever is left over."""
    if slug is not None:
        return {slug: _run_scope(embed, classify, slug)}
    summary = {}
    for name in backlog_order():
        logger.info(f"GPU lane backlog: {name}")
        summary[name] = _run_scope(embed, classify, name)
    summary["rest"] = _run_scope(embed, classify, None)
    return summary
