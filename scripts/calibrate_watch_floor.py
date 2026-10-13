"""
Calibrate SEARCH_FLOOR (athena/pipeline/watches.py): how close a new feed item must be to a followed search.

  python3 -m scripts.calibrate_watch_floor dump  [--out FILE]   # each query's 30 closest feed items, to label
  python3 -m scripts.calibrate_watch_floor score [--out FILE]   # precision and recall per floor, dev and test

``dump`` writes one JSON line per (query, item) with ``relevant: null``; set it to true or false by reading the
title and abstract, then run ``score``. Recall counts the relevant items among the labelled ones (the 30 closest
per query), so it says what a floor gives up, not what the whole feed holds. Pick the floor on dev and confirm it
on test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEV = [
    "parameter-efficient fine-tuning of large language models",
    "diffusion models for image generation",
    "retrieval-augmented generation",
    "multi-object tracking",
    "reinforcement learning from human feedback",
]
TEST = [
    "object detection",
    "AI safety and alignment",
    "speculative decoding for faster LLM inference",
    "NLP for low-resource languages",
    "mixture of experts",
]
TOP = 30
DEFAULT_OUT = Path.home() / ".athena" / "bench" / "watch_floor.jsonl"


def dump(out: Path) -> None:
    from qdrant_client import QdrantClient
    from sqlalchemy import select

    from athena.core.models import ContentItem
    from athena.database.db import SessionLocal
    from athena.pipeline.embedding_worker import COLLECTION_NAME, QDRANT_URL
    from athena.search.local import embed_query

    qdrant = QdrantClient(url=QDRANT_URL)
    rows = []
    with SessionLocal() as session:
        for split, queries in (("dev", DEV), ("test", TEST)):
            for query in queries:
                points = qdrant.query_points(collection_name=COLLECTION_NAME, query=embed_query(query),
                                             limit=TOP).points
                items = {str(i.id): i for i in session.execute(select(ContentItem).where(
                    ContentItem.id.in_([str(p.id) for p in points]))).scalars()}
                for p in points:
                    item = items.get(str(p.id))
                    if item is not None:
                        rows.append({"split": split, "query": query, "item_id": str(p.id),
                                     "similarity": round(float(p.score), 4), "title": item.title,
                                     "abstract": (item.abstract or item.summary or "")[:600], "relevant": None})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"Wrote {len(rows)} rows to {out}")


def score(out: Path) -> None:
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    unlabelled = sum(r["relevant"] is None for r in rows)
    if unlabelled:
        print(f"{unlabelled} rows are not labelled yet")
    floors = [round(0.30 + 0.025 * i, 3) for i in range(17)]
    for split in ("dev", "test"):
        labelled = [r for r in rows if r["split"] == split and r["relevant"] is not None]
        relevant = sum(r["relevant"] for r in labelled)
        print(f"\n{split}: {len(labelled)} labelled, {relevant} relevant")
        print("floor  kept  precision  recall")
        for f in floors:
            kept = [r for r in labelled if r["similarity"] >= f]
            hits = sum(r["relevant"] for r in kept)
            precision = hits / len(kept) if kept else float("nan")
            print(f"{f:5.3f}  {len(kept):4d}  {precision:9.2f}  {hits / relevant if relevant else 0:6.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["dump", "score"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    dump(args.out) if args.command == "dump" else score(args.out)
