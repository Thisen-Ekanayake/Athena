#!/usr/bin/env python3
"""
Athena Health Dashboard

Shows fetch success rate per source from the fetch_logs table.
Usage: python3 scripts/health_dashboard.py [--hours 48]
"""
import sys
import os
import argparse
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import select

# Ensure athena is in path before importing local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import SessionLocal  # noqa: E402
from athena.core.models import Source, FetchLog  # noqa: E402
from athena.core.redis_client import get_redis  # noqa: E402


def get_health_report(hours: int = 48):
    load_dotenv()
    lookback = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    with SessionLocal() as session:
        sources = session.execute(select(Source).order_by(Source.name)).scalars().all()

        print(f"\n{'='*65}")
        print(f"  ATHENA HEALTH DASHBOARD  (last {hours}h)")
        print(f"{'='*65}")
        print(f"  {'Source':<30} {'Status':<10} {'Runs':>5}  {'OK':>5}  {'ERR':>5}  {'Rate':>7}")
        print(f"  {'-'*60}")

        for source in sources:
            logs = session.execute(
                select(FetchLog)
                .where(FetchLog.source_id == source.id)
                .where(FetchLog.created_at >= lookback)
            ).scalars().all()

            total = len(logs)
            successes = sum(1 for log in logs if log.status == "success")
            errors = total - successes
            rate = (successes / total * 100) if total > 0 else 0
            active_flag = "✅" if source.is_active else "❌"

            print(f"  {source.name:<30} {active_flag:<10} {total:>5}  {successes:>5}  {errors:>5}  {rate:>6.1f}%")

        # DLQ status
        r = get_redis()
        dlq_len = r.llen("athena:dlq")
        embed_queue = r.llen("athena:embedding_queue")

        print(f"\n  Dead-Letter Queue (athena:dlq):       {dlq_len} items")
        print(f"  Embedding Queue (athena:embedding_queue): {embed_queue} items")
        print(f"{'='*65}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Athena Health Dashboard")
    parser.add_argument("--hours", type=int, default=48, help="Lookback window in hours")
    args = parser.parse_args()
    get_health_report(hours=args.hours)
