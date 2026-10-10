"""
The GPU lane: one model on the 8 GB card at a time.

Qwen3-Embedding-8B (4.7 GB) and Qwen3.5-9B (5.7 GB) do not fit together, so
a lane run starts the embedder, embeds every pending chunk, stops it, then
starts the 9B and labels every pending citing sentence. It runs on the
single-concurrency Celery ``evolution`` queue so two lanes never compete for
the card. A llama-server already listening on a port is reused instead of
started, provided it serves the expected model.

Settings (env or the settings table): LLAMA_SERVER_BIN, EVOLUTION_EMBED_MODEL,
EVOLUTION_CHAT_MODEL (GGUF paths), EVOLUTION_EMBED_URL, EVOLUTION_CHAT_URL.
"""
from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
from loguru import logger

from athena.core.config_store import get_setting
from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution import vectors
from athena.evolution.classify import Classifier

REPO_ROOT = Path(__file__).resolve().parents[2]
# Phase 0: throughput is the same with one slot as with eight, and every input must fit one ubatch.
MAX_CHUNK_TOKENS = 900
EMBED_BATCH = 8
FETCH = 256
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
    """Run llama-server for the duration of the block, or reuse one already serving ``model``."""
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
    """Trim ``text`` until it fits MAX_CHUNK_TOKENS. Formula-heavy text runs near four tokens a word."""
    trimmed = False
    while True:
        tokens = len(http.post(f"{url}/tokenize", json={"content": text}).json()["tokens"])
        if tokens <= MAX_CHUNK_TOKENS:
            return text, trimmed
        words = text.split()
        text = " ".join(words[:max(20, int(len(words) * 0.9 * MAX_CHUNK_TOKENS / tokens))])
        trimmed = True


def embed_pending(limit: int | None = None) -> dict:
    """Embed chunks that have no vector yet and write them to Qdrant."""
    vectors.ensure_collection()
    url, server = embed_server()
    done = trimmed = 0
    with server, httpx.Client(timeout=600.0) as http, SessionLocal() as session:
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
                resp = http.post(f"{url}/v1/embeddings", json={"input": texts})
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                vecs = vectors.truncate(np.asarray([d["embedding"] for d in data]))
                vectors.upsert([(chunk.id, vec, {"paper_id": str(paper.id), "topic_ids": topics.get(paper.id, []),
                                                 "year": paper.year, "section_type": chunk.section_type,
                                                 "position": chunk.position})
                                for (chunk, paper, _), vec in zip(batch, vecs)])
                db.mark_embedded(session, [c.id for c, _, _ in batch])
                done += len(batch)
            logger.info(f"Embedded {done} chunks ({done / max(time.time() - start, 1e-6):.1f}/s, {trimmed} trimmed)")
    return {"chunks_embedded": done, "chunks_trimmed": trimmed}


# ── classification ─────────────────────────────────────────────────────


def classify_pending(limit: int | None = None) -> dict:
    """Label cue-bearing citing sentences whose cited paper is in some topic's Tier 2."""
    url, server = chat_server()
    labelled = strict = 0
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
    return {"contexts_labelled": labelled, "strict_links": strict}


def run_gpu_lane(embed: bool = True, classify: bool = True) -> dict:
    """Everything pending, one model at a time."""
    summary = {}
    if embed:
        summary |= embed_pending()
    if classify:
        summary |= classify_pending()
    return summary
