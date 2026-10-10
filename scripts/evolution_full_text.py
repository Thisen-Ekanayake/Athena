"""
Research evolution, Phase 2: full text for each topic's Tier 2 papers, then the GPU lane.

Tier 2 is a topic's milestones, main path and each milestone's strongest successors. The full-text
step downloads their PDFs (arXiv first), parses them with GROBID and stores sections, chunks and
citing sentences; it needs GROBID running (`docker run -d --name athena-grobid -p 8070:8070
grobid/grobid:0.9.1-crf`) but no GPU. The GPU lane then embeds the chunks with Qwen3-Embedding-8B
and labels the citing sentences with Qwen3.5-9B, one model at a time.

Usage:
    python3 scripts/evolution_full_text.py peft                  # full text for one topic, in this process
    python3 scripts/evolution_full_text.py --all --gpu           # every topic, then the GPU lane
    python3 scripts/evolution_full_text.py --gpu-only            # only the GPU lane
    python3 scripts/evolution_full_text.py peft --queue          # hand off to the Celery 'evolution' worker
"""
import argparse
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select  # noqa: E402

from athena.core.models import EvoTopic  # noqa: E402
from athena.database.db import SessionLocal, init_db  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true", help="every built topic")
    ap.add_argument("--reparse", action="store_true", help="parse papers again even if they already have full text")
    ap.add_argument("--limit", type=int, help="at most this many papers per topic (for trying it out)")
    ap.add_argument("--gpu", action="store_true", help="run the GPU lane afterwards")
    ap.add_argument("--gpu-only", action="store_true", help="skip full text; only run the GPU lane")
    ap.add_argument("--no-embed", action="store_true", help="GPU lane: skip embedding")
    ap.add_argument("--no-classify", action="store_true", help="GPU lane: skip labelling")
    ap.add_argument("--queue", action="store_true", help="enqueue on the Celery 'evolution' queue instead")
    args = ap.parse_args()

    init_db()
    slugs = args.slugs
    if args.all:
        with SessionLocal() as session:
            slugs = list(session.execute(select(EvoTopic.slug).where(EvoTopic.status == "ready")).scalars())
    if not slugs and not args.gpu_only:
        ap.error("give one or more topic slugs, --all, or --gpu-only")

    from athena.evolution import tasks
    if not args.gpu_only:
        for slug in slugs:
            if args.queue:
                result = tasks.process_full_text.apply_async(args=[slug, args.reparse], queue="evolution")
                print(f"{slug}: full text queued as task {result.id}")
                continue
            from athena.evolution.fulltext import run_full_text
            summary = run_full_text(slug, reparse=args.reparse, limit=args.limit)
            print(f"\n{slug}:")
            for key, value in summary.items():
                print(f"  {key:24s} {value}")
    if args.gpu or args.gpu_only:
        embed, classify = not args.no_embed, not args.no_classify
        if args.queue:
            result = tasks.run_gpu_lane.apply_async(args=[embed, classify], queue="evolution")
            print(f"GPU lane queued as task {result.id}")
            return
        from athena.evolution.gpu import run_gpu_lane
        summary = run_gpu_lane(embed=embed, classify=classify)
        print("\nGPU lane:")
        for key, value in summary.items():
            print(f"  {key:24s} {value}")


if __name__ == "__main__":
    main()
