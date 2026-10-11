"""
Phase 0 — Qwen3-Embedding-8B throughput, VRAM, and 4096-d vs 1024-d retrieval.

1. Throughput: embeds a fixed sample of section chunks at several
   parallel-slot settings and records tokens/s and peak VRAM.
2. Retrieval (needs labels.csv): compares recall@10 for full 4096-d vectors
   and vectors truncated to 1024-d and renormalised.
     - Q1: a sentence criticising earlier work (Task B, addresses_limitation or criticises)
           should retrieve a chunk of the criticised paper.
     - Q2: a gap sentence (Task A, gap) from a cited paper should retrieve a
           chunk of a paper known to address it.

Usage:
    python -m scripts.evolution_bench.bench_embed                 # throughput + retrieval
    python -m scripts.evolution_bench.bench_embed --skip-throughput
"""
import argparse
import csv
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import requests

from scripts.evolution_bench.common import (
    KNOWN_PAIRS, KNOWN_TITLES, LABELS_PATH, LIMITATION_LABELS, OUT_DIR, PAPERS, RESULTS_PATH, labelled_rows,
    load_parsed,
)
from scripts.evolution_bench.servers import EMBED_PORT, ServerStartError, embed_server

CHUNK_WORDS = 300
# Formula- and table-heavy text runs near 4 tokens per word, so a word cap alone overflowed a
# 2,048-token context (one chunk was 2,366 tokens). Chunks are checked with the real tokenizer.
MAX_CHUNK_TOKENS = 900  # below -ub 1024 and the smallest per-slot context
THROUGHPUT_SAMPLE = 240
CONFIGS = [(1, 2048), (4, 4096), (8, 8192)]  # (parallel slots, total context); >= 1024 tokens per slot
BATCH = 8
TOP_K = 10
TRUNCATE_DIM = 1024
Q1_INSTRUCT = "Given a sentence criticising earlier work, retrieve passages from the paper being criticised"
Q2_INSTRUCT = "Given a limitation stated in a research paper, retrieve passages from later papers that address it"


def build_chunks() -> list[dict]:
    """Pack each section's sentences into ~CHUNK_WORDS-word chunks that never cross sections."""
    chunks = []
    parsed = load_parsed()
    for paper in PAPERS:
        pp = parsed.get(paper.key)
        if pp is None:
            continue
        for sec in pp.sections:
            buf: list[str] = []
            for s in sec.sentences:
                buf.append(s.text)
                if sum(len(b.split()) for b in buf) >= CHUNK_WORDS:
                    chunks.append({"paper": paper.key, "section": sec.section_type,
                                   "text": f"{paper.title}\n{sec.heading}\n{' '.join(buf)}"})
                    buf = []
            if buf:
                chunks.append({"paper": paper.key, "section": sec.section_type,
                               "text": f"{paper.title}\n{sec.heading}\n{' '.join(buf)}"})
    return chunks


def _n_tokens(text: str) -> int:
    r = requests.post(f"http://127.0.0.1:{EMBED_PORT}/tokenize", json={"content": text}, timeout=60)
    r.raise_for_status()
    return len(r.json()["tokens"])


def fit_to_tokens(chunks: list[dict]) -> list[dict]:
    """Halve chunks over MAX_CHUNK_TOKENS until they fit (needs a running embedding server)."""
    out = []
    for chunk in chunks:
        if _n_tokens(chunk["text"]) <= MAX_CHUNK_TOKENS:
            out.append(chunk)
            continue
        title, heading, body = chunk["text"].split("\n", 2)
        words = body.split()
        mid = len(words) // 2
        halves = [" ".join(words[:mid]), " ".join(words[mid:])]
        out += fit_to_tokens([chunk | {"text": f"{title}\n{heading}\n{half}"} for half in halves])
    return out


def load_chunks() -> list[dict]:
    """Section chunks that fit the embedding context, cached so every run embeds the same set."""
    cache = OUT_DIR / "chunks.json"
    if cache.exists():
        return json.loads(cache.read_text())
    with embed_server():
        chunks = fit_to_tokens(build_chunks())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(chunks))
    return chunks


def _post_embeddings(texts: list[str]) -> tuple[list[list[float]], int]:
    r = requests.post(f"http://127.0.0.1:{EMBED_PORT}/v1/embeddings", json={"input": texts}, timeout=600)
    r.raise_for_status()
    body = r.json()
    vecs = [d["embedding"] for d in sorted(body["data"], key=lambda d: d["index"])]
    return vecs, int(body.get("usage", {}).get("prompt_tokens", 0))


def embed_all(texts: list[str], workers: int) -> tuple[np.ndarray, int, float]:
    batches = [texts[i:i + BATCH] for i in range(0, len(texts), BATCH)]
    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_post_embeddings, batches))
    elapsed = time.time() - start
    vecs = np.asarray([v for batch_vecs, _ in results for v in batch_vecs], dtype=np.float32)
    tokens = sum(t for _, t in results)
    return vecs, tokens, elapsed


class VramPeak:
    """Poll nvidia-smi in the background and keep the highest memory.used seen (MiB)."""

    def __init__(self):
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True).stdout.strip()
            if out:
                self.peak = max(self.peak, int(out.splitlines()[0]))
            time.sleep(0.5)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def embed_queries(instruct: str, rows: list[dict], workers: int, dim: int) -> np.ndarray:
    """Embed labelled sentences as queries, with Qwen3-Embedding's instruction prefix."""
    if not rows:
        return np.zeros((0, dim), dtype=np.float32)
    return embed_all([f"Instruct: {instruct}\nQuery: {r['sentence']}" for r in rows], workers)[0]


def normalise(m: np.ndarray) -> np.ndarray:
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def append_results(rows: list[dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new = not RESULTS_PATH.exists()
    with open(RESULTS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "bench", "setting", "metric", "value"])
        if new:
            writer.writeheader()
        writer.writerows(rows)


def run_throughput(chunks: list[dict]) -> list[dict]:
    sample = [c["text"] for c in chunks[:THROUGHPUT_SAMPLE]]
    rows = []
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"\nThroughput on {len(sample)} chunks (~{CHUNK_WORDS} words each)")
    for parallel, ctx in CONFIGS:
        setting = f"np={parallel},ctx={ctx}"
        try:
            with embed_server(parallel=parallel, ctx=ctx), VramPeak() as vram:
                embed_all(sample[:BATCH], workers=1)  # warm-up
                _, tokens, elapsed = embed_all(sample, workers=parallel)
        except ServerStartError as exc:
            print(f"  np={parallel} ctx={ctx}: did not start ({exc})")
            rows.append({"timestamp": stamp, "bench": "embed", "setting": setting, "metric": "start_failed",
                         "value": 1})
            continue
        tps = tokens / elapsed if elapsed else 0.0
        print(f"  np={parallel} ctx={ctx}: {tokens} tokens in {elapsed:.1f}s = {tps:,.0f} tok/s, "
              f"peak VRAM {vram.peak} MiB")
        rows += [{"timestamp": stamp, "bench": "embed", "setting": setting, "metric": "tokens_per_s",
                  "value": round(tps, 1)},
                 {"timestamp": stamp, "bench": "embed", "setting": setting, "metric": "peak_vram_mib",
                  "value": vram.peak}]
    append_results(rows)
    return rows


def recall_at_k(q: np.ndarray, docs: np.ndarray, doc_papers: list[str], exclude: list[str],
                targets: list[set[str]]) -> tuple[float, list[list[int]]]:
    scores = q @ docs.T
    hits, tops = 0, []
    for i in range(len(q)):
        order = [j for j in np.argsort(-scores[i]) if doc_papers[j] != exclude[i]][:TOP_K]
        tops.append(order)
        hits += any(doc_papers[j] in targets[i] for j in order)
    return hits / len(q) if len(q) else float("nan"), tops


def run_retrieval(chunks: list[dict], parallel: int, ctx: int):
    try:
        b_rows = [r for r in labelled_rows("B") if r["label"] in LIMITATION_LABELS and r["cited"] in KNOWN_TITLES]
        resolvers = {}
        for citing, cited in KNOWN_PAIRS:
            resolvers.setdefault(cited, set()).add(citing)
        a_rows = [r for r in labelled_rows("A") if r["label"] == "gap" and r["paper"] in resolvers]
    except FileNotFoundError:
        print(f"\nNo {LABELS_PATH.name} yet; skipping the retrieval test.")
        return

    have_chunks = {c["paper"] for c in chunks}
    q1 = [r for r in b_rows if r["cited"] in have_chunks]
    q2 = [r for r in a_rows if resolvers[r["paper"]] & have_chunks]
    if not q1 and not q2:
        print("\nNo labelled queries for the retrieval test yet; label Tasks A and B first.")
        return

    cache = OUT_DIR / "chunk_vecs.npy"
    with embed_server(parallel=parallel, ctx=ctx):
        if cache.exists() and len(np.load(cache)) == len(chunks):
            docs = np.load(cache)
        else:
            docs, _, _ = embed_all([c["text"] for c in chunks], workers=parallel)
            np.save(cache, docs)
        q1_vecs = embed_queries(Q1_INSTRUCT, q1, parallel, docs.shape[1])
        q2_vecs = embed_queries(Q2_INSTRUCT, q2, parallel, docs.shape[1])

    doc_papers = [c["paper"] for c in chunks]
    stamp = datetime.now().isoformat(timespec="seconds")
    rows = []
    print(f"\nRetrieval over {len(chunks)} chunks, recall@{TOP_K} (own paper excluded)")
    for name, q, qrows, targets in [
        ("Q1 criticism -> criticised paper", q1_vecs, q1, [{r["cited"]} for r in q1]),
        ("Q2 gap -> resolving paper", q2_vecs, q2, [resolvers[r["paper"]] for r in q2]),
    ]:
        if not len(q):
            print(f"  {name}: no labelled queries")
            continue
        exclude = [r["paper"] for r in qrows]
        full, tops_full = recall_at_k(normalise(q), normalise(docs), doc_papers, exclude, targets)
        cut, tops_cut = recall_at_k(normalise(q[:, :TRUNCATE_DIM]), normalise(docs[:, :TRUNCATE_DIM]),
                                    doc_papers, exclude, targets)
        overlap = np.mean([len(set(a) & set(b)) / TOP_K for a, b in zip(tops_full, tops_cut)])
        print(f"  {name}: n={len(q)}  4096-d {full:.2f}  {TRUNCATE_DIM}-d {cut:.2f}  "
              f"drop {100 * (full - cut):+.1f} pts  top-{TOP_K} overlap {overlap:.2f}")
        key = name.split()[0]
        for metric, value in [("recall_4096", full), (f"recall_{TRUNCATE_DIM}", cut), ("top10_overlap", overlap)]:
            rows.append({"timestamp": stamp, "bench": "embed", "setting": key, "metric": metric,
                         "value": round(float(value), 3)})
    append_results(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-throughput", action="store_true")
    ap.add_argument("--parallel", type=int, default=4, help="slots for the retrieval run")
    ap.add_argument("--ctx", type=int, default=4096)
    args = ap.parse_args()

    chunks = load_chunks()
    print(f"{len(chunks)} chunks from {len({c['paper'] for c in chunks})} papers")
    if not args.skip_throughput:
        run_throughput(chunks)
    run_retrieval(chunks, args.parallel, args.ctx)


if __name__ == "__main__":
    main()
