"""
Phase 0 — blind spot-check of the labels in labels.csv.

labels.csv was labelled by Claude. This writes spotcheck.csv: 20 of those
rows with the labels removed, for a person to label independently. Then
``--compare`` reports how often the two agree and lists every disagreement.

Usage:
    python -m scripts.evolution_bench.spotcheck            # write spotcheck.csv
    python -m scripts.evolution_bench.spotcheck --compare  # after filling in its `label` column
"""
import argparse
import csv
import random

from scripts.evolution_bench.common import BENCH_DIR, LIMITATION_LABELS, TASK_LABELS, read_labels

SPOTCHECK_PATH = BENCH_DIR / "spotcheck.csv"
COLUMNS = ["id", "task", "paper", "cited", "section", "sentence", "label", "notes"]
# Task B limitation rows decide the 9B's role, so they get the most checks.
PLAN = [("B", True, 6), ("B", False, 6), ("A", True, 3), ("A", False, 3), ("C", None, 2)]


def make():
    if SPOTCHECK_PATH.exists() and any(r["label"].strip() for r in read_labels(SPOTCHECK_PATH)):
        raise SystemExit(f"{SPOTCHECK_PATH} already has labels; delete it first to start over.")
    rows = read_labels()
    rng = random.Random(7)
    picks = []
    for task, positive, n in PLAN:
        pool = [r for r in rows if r["task"] == task]
        if task == "B":
            pool = [r for r in pool if (r["label"] in LIMITATION_LABELS) == positive]
        elif task == "A":
            pool = [r for r in pool if (r["label"] == "gap") == positive]
        picks += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(picks)
    with open(SPOTCHECK_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in picks:
            writer.writerow({c: r[c] for c in COLUMNS} | {"label": "", "notes": ""})
    print(f"Wrote {len(picks)} rows to {SPOTCHECK_PATH}. Fill the `label` column, then run with --compare.")


def compare():
    mine = {r["id"]: r for r in read_labels(SPOTCHECK_PATH) if r["label"].strip()}
    gold = {r["id"]: r for r in read_labels()}
    if not mine:
        raise SystemExit(f"No labels in {SPOTCHECK_PATH} yet.")
    bad = [i for i, r in mine.items() if r["label"].strip() not in TASK_LABELS[r["task"]]]
    if bad:
        raise SystemExit(f"Rows {bad} have labels outside the allowed set.")

    agree = sum(mine[i]["label"].strip() == gold[i]["label"] for i in mine)
    print(f"Exact agreement: {agree}/{len(mine)}")
    b_ids = [i for i in mine if mine[i]["task"] == "B"]
    if b_ids:
        b_agree = sum((mine[i]["label"].strip() in LIMITATION_LABELS) == (gold[i]["label"] in LIMITATION_LABELS)
                      for i in b_ids)
        print(f"Task B 'states a limitation' agreement: {b_agree}/{len(b_ids)}")
    for i in sorted(mine):
        if mine[i]["label"].strip() != gold[i]["label"]:
            print(f"\n{i} [{gold[i]['task']}] you: {mine[i]['label'].strip()}  claude: {gold[i]['label']}"
                  f"{'  (' + gold[i]['notes'] + ')' if gold[i]['notes'] else ''}")
            print(f"    {gold[i]['sentence'][:220]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    compare() if args.compare else make()


if __name__ == "__main__":
    main()
