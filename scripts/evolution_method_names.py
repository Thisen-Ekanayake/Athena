"""
Fetch the names citing papers use for each topic's top candidates (ROADMAP E9).

Reads Semantic Scholar's citing sentences, one request per paper; without an
API key that is slow (a few seconds a request) but cached for 30 days. The next
build of each topic uses the names as a milestone-score feature.

Usage:
    python -m scripts.evolution_method_names object-detection peft
    python -m scripts.evolution_method_names --all [--top 150] [--force]
"""
import argparse

from sqlalchemy import select

from athena.core.models import EvoTopic
from athena.database.db import SessionLocal
from athena.evolution.method_names import TOP_CANDIDATES, fetch_method_names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slugs", nargs="*")
    parser.add_argument("--all", action="store_true", help="every built topic")
    parser.add_argument("--top", type=int, default=TOP_CANDIDATES)
    parser.add_argument("--force", action="store_true", help="fetch again even when fetched recently")
    args = parser.parse_args()
    slugs = args.slugs
    if args.all:
        with SessionLocal() as session:
            slugs = list(session.execute(select(EvoTopic.slug).where(EvoTopic.built_at.isnot(None))
                                         .order_by(EvoTopic.slug)).scalars())
    for slug in slugs:
        print(slug, fetch_method_names(slug, top=args.top, force=args.force))


if __name__ == "__main__":
    main()
