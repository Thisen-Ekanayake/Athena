"""
Fetch citations per year from OpenAlex for every built map's papers (athena.evolution.momentum).

New builds and refreshes do this themselves; this fills in maps built before. About one request per 100 papers,
through the OpenAlex cache.

Usage:
    python -m scripts.backfill_citation_years            # papers with none, or older than 30 days
    python -m scripts.backfill_citation_years --force    # every paper again
"""
import argparse
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402

from athena.core.models import EvoTopic  # noqa: E402
from athena.database.db import SessionLocal  # noqa: E402
from athena.evolution.momentum import refresh_topic_years  # noqa: E402
from athena.evolution.openalex import OpenAlexClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="fetch every paper again")
    args = parser.parse_args()
    client = OpenAlexClient()
    with SessionLocal() as session:
        topics = session.execute(select(EvoTopic).where(EvoTopic.built_at.isnot(None))).scalars().all()
        for topic in topics:
            n = refresh_topic_years(session, topic, client, force=args.force)
            print(f"{topic.slug}: {n} papers")
    print(f"OpenAlex: {client.requests} requests, {client.cache_hits} from cache, ${client.spent_usd:.4f}")


if __name__ == "__main__":
    main()
