"""
The GPU lane: one model on the 8 GB card at a time.

Qwen3-Embedding-8B (4.7 GB) and Qwen3.5-9B (5.7 GB) do not fit together, so
a lane run starts the 9B and labels every pending citing sentence and gap
candidate, stops it, then starts the embedder for every chunk and gap
statement without a vector and searches loose links, and finally rebuilds
the gap themes on the CPU. It runs on the single-concurrency Celery
``evolution`` queue so two lanes never compete for the card. A llama-server
already listening on a port is reused instead of started, provided it serves
the expected model.

Settings (env or the settings table): LLAMA_SERVER_BIN, EVOLUTION_EMBED_MODEL,
EVOLUTION_CHAT_MODEL (GGUF paths), EVOLUTION_EMBED_URL, EVOLUTION_CHAT_URL.
"""
from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
import numpy as np
from loguru import logger

from sqlalchemy import select

from athena.core.config_store import get_setting
from athena.core.models import EvoTopic
from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution import vectors
from athena.evolution.classify import Classifier, auth_headers, managed_servers
from athena.evolution.gaps import build_themes

REPO_ROOT = Path(__file__).resolve().parents[2]
# Phase 0: throughput is the same with one slot as with eight, and every input must fit one ubatch.
MAX_CHUNK_TOKENS = 900
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
LOG_DIR = Path.home() / ".athena" / "evolution" / "logs"


class ServerStartError(RuntimeError):
    """llama-server exited before becoming healthy (usually out of VRAM)."""


def _healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _served_model(url: str) -> str:
    try:
        data = httpx.get(f"{url}/v1/models", timeout=5).json().get("data") or [{}]
        return str(data[0].get("id", ""))
    except (httpx.HTTPError, ValueError):
        return ""


@contextmanager
def llama_server(url: str, model: Path, args: list[str], log_name: str):
    """Run llama-server for the duration of the block, or reuse one already serving ``model``.

    With external endpoints (EVOLUTION_MANAGED_SERVERS=false) nothing is started.
    """
    if not managed_servers():
        logger.info(f"Using the external endpoint at {url}")
        yield
        return
    if _healthy(url):
        served = _served_model(url)
        if served and model.stem.lower() not in served.lower() and model.name.lower() not in served.lower():
            raise ServerStartError(f"{url} is serving {served!r}, not {model.name}; stop it or change the URL")
        logger.info(f"Reusing llama-server at {url}")
        yield
        return
    if not model.exists():
        raise ServerStartError(f"Model file not found: {model}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    port = str(urlparse(url).port or 8080)
    binary = get_setting("LLAMA_SERVER_BIN", "llama-server")
    with open(log_path, "w") as log:
        proc = subprocess.Popen([binary, "--port", port, "-m", str(model), *args], stdout=log,
                                stderr=subprocess.STDOUT)
    try:
        logger.info(f"Starting llama-server for {model.name} on :{port} (log: {log_path})")
        while not _healthy(url):
            if proc.poll() is not None:
                raise ServerStartError(f"llama-server exited early, see {log_path}")
            time.sleep(1)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def _model_path(setting: str, default: str) -> Path:
    path = Path(get_setting(setting, default))
    return path if path.is_absolute() else REPO_ROOT / path


def embed_server():
    url = get_setting("EVOLUTION_EMBED_URL", "http://127.0.0.1:8081").rstrip("/")
    model = _model_path("EVOLUTION_EMBED_MODEL", "models/Qwen3-Embedding-8B-Q4_K_M.gguf")
    args = ["--embedding", "--pooling", "last", "-ngl", "99", "-c", "2048", "-np", "1", "-b", "2048", "-ub", "1024"]
    return url, llama_server(url, model, args, "embed-server.log")


def chat_server():
    url = get_setting("EVOLUTION_CHAT_URL", "http://127.0.0.1:8080").rstrip("/")
    model = _model_path("EVOLUTION_CHAT_MODEL", "models/Qwen3.5-9B-Q4_K_M.gguf")
    # Thinking is off per request; the budget only guards against a template that ignores that.
    args = ["-ngl", "99", "-c", "8192", "-np", "1", "--jinja", "--reasoning-budget", "512"]
    return url, llama_server(url, model, args, "chat-server.log")


# ── embedding ──────────────────────────────────────────────────────────


def _fit(http: httpx.Client, url: str, text: str) -> tuple[str, bool]:
    """Trim ``text`` until it fits MAX_CHUNK_TOKENS. Formula-heavy text runs near four tokens a word.

    External endpoints have no /tokenize, so there the text is cut at a word count instead.
    """
    if not managed_servers():
        words = text.split()
        return " ".join(words[:EXTERNAL_MAX_WORDS]), len(words) > EXTERNAL_MAX_WORDS
    trimmed = False
    while True:
        tokens = len(http.post(f"{url}/tokenize", json={"content": text}).json()["tokens"])
        if tokens <= MAX_CHUNK_TOKENS:
            return text, trimmed
        words = text.split()
        text = " ".join(words[:max(20, int(len(words) * 0.9 * MAX_CHUNK_TOKENS / tokens))])
        trimmed = True


def _embed(http: httpx.Client, url: str, texts: list[str]) -> np.ndarray:
    body: dict = {"input": texts, "model": get_setting("EVOLUTION_EMBED_MODEL_NAME", "qwen3-embedding-8b")}
    if get_setting("EVOLUTION_EMBED_DIMENSIONS"):  # OpenAI's text-embedding-3 models shorten vectors themselves
        body["dimensions"] = int(get_setting("EVOLUTION_EMBED_DIMENSIONS"))
    resp = http.post(f"{url}/v1/embeddings", json=body)
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    raw = np.asarray([d["embedding"] for d in data])
    if raw.shape[1] < vectors.DIM:
        raise ValueError(f"The embedding model returns {raw.shape[1]} dimensions; the collections need at least "
                         f"{vectors.DIM}. Use a model with more, or rebuild the collections for this one.")
    return vectors.truncate(raw)


def _embed_chunks(http: httpx.Client, url: str, session, limit: int | None) -> dict:
    done = trimmed = 0
    start = time.time()
    while limit is None or done < limit:
        rows = db.pending_chunks(session, FETCH if limit is None else min(FETCH, limit - done))
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


def _embed_gaps(http: httpx.Client, url: str, session) -> int:
    """Gap statements as documents: the sentence alone, so themes group by gap rather than by paper."""
    vectors.ensure_collection(name=vectors.GAP_COLLECTION)
    done = 0
    while rows := db.pending_gap_vectors(session, FETCH):
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i:i + EMBED_BATCH]
            vecs = _embed(http, url, [_fit(http, url, g.sentence)[0] for g, _ in batch])
            vectors.upsert([(g.id, vec, {"paper_id": str(g.paper_id), "origin": g.origin, "year": year})
                            for (g, year), vec in zip(batch, vecs)], name=vectors.GAP_COLLECTION)
            db.mark_gaps(session, [g.id for g, _ in batch], "embedded_at")
            done += len(batch)
    logger.info(f"Embedded {done} gap statements")
    return done


def _embed_abstracts(http: httpx.Client, url: str, session) -> int:
    """Tier 1: every topic paper's title and abstract, for topic search."""
    vectors.ensure_collection(name=vectors.ABSTRACT_COLLECTION)
    done = 0
    while papers := db.pending_abstracts(session, FETCH):
        for i in range(0, len(papers), EMBED_BATCH):
            batch = papers[i:i + EMBED_BATCH]
            vecs = _embed(http, url, [_fit(http, url, f"{p.title}\n{p.abstract or ''}")[0] for p in batch])
            vectors.upsert([(p.id, vec, {"paper_id": str(p.id), "year": p.year}) for p, vec in zip(batch, vecs)],
                           name=vectors.ABSTRACT_COLLECTION)
            db.mark_abstracts(session, [p.id for p in batch])
            done += len(batch)
    logger.info(f"Embedded {done} abstracts")
    return done


def _loose_links(http: httpx.Client, url: str, session) -> int:
    """For each gap statement, the later papers whose abstract, introduction or method matches it best."""
    found = 0
    while rows := db.pending_loose(session, FETCH):
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


def embed_pending(limit: int | None = None) -> dict:
    """Embed chunks and gap statements that have no vector yet, search loose links, then embed abstracts."""
    vectors.ensure_collection()
    url, server = embed_server()
    with server, httpx.Client(timeout=600.0, headers=auth_headers()) as http, SessionLocal() as session:
        summary = _embed_chunks(http, url, session, limit)
        if limit is None:
            summary["gaps_embedded"] = _embed_gaps(http, url, session)
            summary["loose_links"] = _loose_links(http, url, session)
            summary["abstracts_embedded"] = _embed_abstracts(http, url, session)
    return summary


# ── classification ─────────────────────────────────────────────────────


def classify_pending(limit: int | None = None) -> dict:
    """Label cue-bearing citing sentences whose cited paper is in some topic's Tier 2, then gap candidates."""
    url, server = chat_server()
    labelled = strict = gaps = candidates = 0
    with server, SessionLocal() as session:
        clf = Classifier(base_url=url)
        cited_ids = db.all_tier2_ids(session)
        start = time.time()
        while limit is None or labelled < limit:
            rows = db.pending_contexts(session, cited_ids, 64 if limit is None else min(64, limit - labelled))
            if not rows:
                break
            out = []
            for ctx, citing_title, cited_title in rows:
                v = clf.classify(citing_title, cited_title, ctx.sentence, ctx.marked)
                # A failed answer is stored as "unknown" so it is not retried forever.
                out.append({"id": ctx.id, "label": v.label or "unknown", "attributed": v.attributed,
                            "model": clf.model})
                strict += v.strict
            db.save_labels(session, out)
            labelled += len(out)
            logger.info(f"Labelled {labelled} citing sentences, {strict} strict "
                        f"({labelled / max(time.time() - start, 1e-6):.1f}/s)")
        while limit is None and (rows := db.pending_gap_candidates(session, 64)):
            out = []
            for gap, title in rows:
                label = clf.is_gap(title, gap.section_type, gap.sentence) or "unknown"
                out.append({"id": gap.id, "label": label, "model": clf.model})
                gaps += label == "gap"
            db.save_gap_labels(session, out)
            candidates += len(out)
            logger.info(f"Labelled {candidates} gap candidates, {gaps} gaps")
    return {"contexts_labelled": labelled, "strict_links": strict, "gap_candidates_labelled": candidates,
            "gaps": gaps}


def build_all_themes() -> dict:
    """Gap themes for every built topic, from the gap statements' vectors. CPU only."""
    out = {}
    with SessionLocal() as session:
        topics = list(session.execute(select(EvoTopic).where(EvoTopic.status == "ready")).scalars())
        for topic in topics:
            rows = db.topic_gap_rows(session, topic)
            vecs = vectors.vectors_for([r["id"] for r in rows]) if rows else {}
            rows = [r for r in rows if r["id"] in vecs]
            themes = build_themes(rows, np.asarray([vecs[r["id"]] for r in rows])) if rows else []
            db.save_themes(topic.id, themes)
            out[topic.slug] = {"gap_statements": len(rows), "themes": len(themes),
                               "persisting": sum(t["status"] == "persisting" for t in themes)}
    logger.info(f"Gap themes: {out}")
    return out


def run_gpu_lane(embed: bool = True, classify: bool = True) -> dict:
    """Everything pending, one model at a time: the 9B first, then the embedder, then themes on the CPU."""
    summary = {}
    if classify:
        summary |= classify_pending()
    with SessionLocal() as session:
        summary["citing_gaps"] = db.sync_citing_gaps(session)
    if embed:
        summary |= embed_pending()
        summary["themes"] = build_all_themes()
    return summary
