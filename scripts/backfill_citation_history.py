"""
Fill in citation momentum now instead of waiting for the daily run (athena.pipeline.momentum).

Refreshes every feed paper's citation count from Semantic Scholar, rebuilds the history of every paper that has
citations (one keyless request each, about 3 s apart), takes today's snapshots and sets the 7- and 30-day gains.
Marks the day as done, so the hourly task doesn't repeat it.

Usage:
    python -m scripts.backfill_citation_history
    python -m scripts.backfill_citation_history --redo   # rebuild histories that were rebuilt before
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from athena.core.config_store import set_setting  # noqa: E402
from athena.database.db import SessionLocal  # noqa: E402
from athena.evolution.semantic_scholar import SemanticScholarClient  # noqa: E402
from athena.pipeline import momentum  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--redo", action="store_true", help="rebuild histories that were already rebuilt")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        if args.redo:
            for item in momentum._papers(session, now):
                ss = (item.extra_data or {}).get("semantic_scholar") or {}
                if ss.get("history_rebuilt"):
                    item.extra_data = {**item.extra_data, "semantic_scholar": {
                        k: v for k, v in ss.items() if k != "history_rebuilt"}}
            session.commit()
        summary = momentum.run(session, SemanticScholarClient(), now, rebuilds=None)
    set_setting(momentum.DAY_MARKER, now.date().isoformat())
    print(summary)


if __name__ == "__main__":
    main()
