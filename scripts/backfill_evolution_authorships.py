"""
Fill evo_papers.authorships (OpenAlex author and institution IDs) for papers built before it existed.

Builds store authorships from now on; this fetches them for the rest with
OpenAlex list calls of 100 works each ($0.0001 per call, so about $0.01 for
8,000 papers). Safe to run again: it only asks for papers that have none.

Usage:
    python -m scripts.backfill_evolution_authorships [--limit 1000]
"""
import argparse

from loguru import logger
from sqlalchemy import or_, select, update

from athena.core.models import EvoPaper
from athena.database.db import SessionLocal
from athena.core.openalex import IDS_PER_FILTER, OpenAlexClient


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="at most this many papers")
    args = parser.parse_args()
    client = OpenAlexClient()
    with SessionLocal() as session:
        empty = or_(EvoPaper.authorships.is_(None), EvoPaper.authorships == [])
        ids = list(session.execute(select(EvoPaper.openalex_id).where(empty).order_by(EvoPaper.openalex_id)
                                   .limit(args.limit)).scalars())
        logger.info(f"{len(ids)} papers without authorships")
        filled = 0
        for start in range(0, len(ids), IDS_PER_FILTER):
            chunk = ids[start:start + IDS_PER_FILTER]
            for work in client.get_works(chunk):
                if work.authorships and work.openalex_id in chunk:
                    session.execute(update(EvoPaper).where(EvoPaper.openalex_id == work.openalex_id)
                                    .values(authorships=work.authorships))
                    filled += 1
            session.commit()
            logger.info(f"{min(start + IDS_PER_FILTER, len(ids))}/{len(ids)} looked up, {filled} filled")
    print(f"Filled authorships for {filled} of {len(ids)} papers")


if __name__ == "__main__":
    main()
