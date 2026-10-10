"""
Build research-evolution topics: OpenAlex corpus, citation graph, milestones.

Usage:
    python3 scripts/build_evolution_topic.py peft                 # build now, in this process
    python3 scripts/build_evolution_topic.py --all
    python3 scripts/build_evolution_topic.py peft --queue         # hand off to the Celery 'evolution' worker
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
    ap.add_argument("--all", action="store_true", help="build every seeded topic")
    ap.add_argument("--queue", action="store_true", help="enqueue on the Celery 'evolution' queue instead")
    args = ap.parse_args()

    init_db()
    slugs = args.slugs
    if args.all:
        with SessionLocal() as session:
            slugs = list(session.execute(select(EvoTopic.slug)).scalars())
    if not slugs:
        ap.error("give one or more topic slugs, or --all")

    for slug in slugs:
        if args.queue:
            from athena.evolution.tasks import build_topic as build_task
            result = build_task.apply_async(args=[slug], queue="evolution")
            print(f"{slug}: queued as task {result.id}")
            continue
        from athena.evolution.build import build_topic
        summary = build_topic(slug)
        print(f"\n{slug}:")
        for key, value in summary.items():
            print(f"  {key:24s} {value}")


if __name__ == "__main__":
    main()
