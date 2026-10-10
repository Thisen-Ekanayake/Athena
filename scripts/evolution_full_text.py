"""
Research evolution, Phase 2: full text for each topic's Tier 2 papers.

Tier 2 is a topic's milestones, main path and each milestone's strongest successors. The full-text
step downloads their PDFs (arXiv first), parses them with GROBID and stores sections, chunks and
citing sentences; it needs GROBID running (`docker run -d --name athena-grobid -p 8070:8070
grobid/grobid:0.9.1-crf`) but no GPU.

Usage:
    python3 scripts/evolution_full_text.py peft                  # full text for one topic, in this process
    python3 scripts/evolution_full_text.py --all                 # every built topic
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
    ap.add_argument("--queue", action="store_true", help="enqueue on the Celery 'evolution' queue instead")
    args = ap.parse_args()

    init_db()
    slugs = args.slugs
    if args.all:
        with SessionLocal() as session:
            slugs = list(session.execute(select(EvoTopic.slug).where(EvoTopic.status == "ready")).scalars())
    if not slugs:
        ap.error("give one or more topic slugs, or --all")

    from athena.evolution import tasks
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


if __name__ == "__main__":
    main()
