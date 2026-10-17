"""How much information the feed score and the clusters carry. Read-only.

Per category and overall: each signal's spread (from the latest content_scores row of each item) and the
score's correlation with recency; the source mix of the top of the Score feed; and how much the clusters
follow the source (normalised mutual information, against a shuffled baseline).

    python3 scripts/feed_report.py [--top 100]
"""
import argparse
import os
import random
import sys
from collections import Counter, defaultdict

import numpy as np
from sqlalchemy import inspect, text

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import SessionLocal, engine  # noqa: E402


def _signals() -> list:
    """The signal columns content_scores has now (whatever was dropped is simply not reported)."""
    cols = [c["name"] for c in inspect(engine).get_columns("content_scores")]
    return [c for c in cols if c.endswith("_score") and c != "composite_score"]


def scores(session) -> None:
    signals = _signals()
    picked = ", ".join(f"s.{c}" for c in signals)
    rows = session.execute(text(f"""
        SELECT i.category, i.score, {picked}
        FROM content_items i
        JOIN LATERAL (SELECT * FROM content_scores s WHERE s.item_id = i.id
                      ORDER BY s.computed_at DESC NULLS LAST LIMIT 1) s ON true
        WHERE i.score IS NOT NULL
    """)).all()
    if not rows:
        print("No scored items.")
        return
    groups = defaultdict(list)
    for r in rows:
        groups[str(r[0])].append(r)
        groups["ALL"].append(r)
    recency = signals.index("recency_score") + 2 if "recency_score" in signals else None

    print(f"Scores ({len(rows)} items, latest score row each)\n")
    header = f"{'category':<16}{'n':>6}  " + "".join(f"{c.removesuffix('_score'):>22}" for c in signals) \
        + f"{'corr(score,rec)':>18}"
    print(header)
    print(f"{'':<24}" + "".join(f"{'min / max / sd':>22}" for _ in signals))
    for name, group in sorted(groups.items(), key=lambda kv: kv[0] == "ALL"):
        m = np.array([[float(v) if v is not None else np.nan for v in r[1:]] for r in group])
        cells = []
        for j in range(1, m.shape[1]):
            col = m[:, j][~np.isnan(m[:, j])]
            cells.append(f"{col.min():.2f} / {col.max():.2f} / {col.std():.3f}" if len(col) else "-")
        corr = "-"
        if recency is not None:
            a, b = m[:, 0], m[:, recency - 1]
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() > 2 and a[ok].std() > 0 and b[ok].std() > 0:
                corr = f"{np.corrcoef(a[ok], b[ok])[0, 1]:.3f}"
        print(f"{name:<16}{len(group):>6}  " + "".join(f"{c:>22}" for c in cells) + f"{corr:>18}")
    constant = [c for c in signals
                if np.nanstd(np.array([float(r[2 + signals.index(c)] or 0) for r in rows])) == 0]
    print(f"\nConstant across all items: {', '.join(constant) or 'none'}")


def top_sources(session, top: int) -> None:
    rows = session.execute(text("""
        SELECT s.name FROM content_items i JOIN sources s ON s.id = i.source_id
        WHERE i.score IS NOT NULL ORDER BY i.score DESC LIMIT :n
    """), {"n": top}).scalars().all()
    total = session.execute(text("""
        SELECT s.name, count(*) FROM content_items i JOIN sources s ON s.id = i.source_id GROUP BY s.name
    """)).all()
    corpus = sum(n for _, n in total) or 1
    print(f"\nTop {len(rows)} by score, by source (share of the corpus in brackets)")
    for name, n in Counter(rows).most_common():
        share = dict(total).get(name, 0) / corpus
        print(f"  {n:>4}  {name}  ({share:.0%})")


def clusters(session) -> None:
    rows = session.execute(text("""
        SELECT i.cluster_id::text, s.name, c.label FROM content_items i
        JOIN sources s ON s.id = i.source_id JOIN clusters c ON c.id = i.cluster_id
        WHERE c.is_active
    """)).all()
    if not rows:
        print("\nNo items in active clusters.")
        return
    from sklearn.metrics import normalized_mutual_info_score as nmi
    cl = [r[0] for r in rows]
    src = [r[1] for r in rows]
    shuffled = src[:]
    random.Random(0).shuffle(shuffled)
    print(f"\nClusters: {len(set(cl))} active, {len(rows)} items")
    print(f"  NMI(cluster, source) = {nmi(src, cl):.3f}   (shuffled sources: {nmi(shuffled, cl):.3f})")
    by = defaultdict(Counter)
    labels = {}
    for c, s, label in rows:
        by[c][s] += 1
        labels[c] = label
    pure = 0
    for c, counts in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(counts.values())
        name, top = counts.most_common(1)[0]
        pure += top / n >= 0.8
        print(f"  {n:>5}  {top / n:>4.0%} {name:<24} {labels[c] or ''}")
    print(f"  {pure} of {len(by)} clusters are at least 80% one source")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=100, help="how much of the top of the Score feed to count")
    args = parser.parse_args()
    with SessionLocal() as session:
        scores(session)
        top_sources(session, args.top)
        clusters(session)


if __name__ == "__main__":
    main()
