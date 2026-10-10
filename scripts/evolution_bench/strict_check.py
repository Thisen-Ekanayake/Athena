"""
Phase 2 — hand check of strict gap -> resolution links.

Phase 2 is done when a hand-checked sample of strict links meets the Phase 0
precision target (0.8). This samples citing sentences the 9B labelled, blind:
strict links (limitation label + attributed to the cited paper) and, to
estimate what the filter misses, cue sentences it did not mark strict. The
sheet does not say which is which.

For each row, answer in `answer`: does the sentence state a limitation of the
CITED paper's own method, model or results? (The cited paper's citation is
marked [[ like this ]].)

    yes     it does (alone or as one of several works criticised together)
    no      it does not: the problem belongs to other work, the cited paper is only the source
            of a number or finding, or no problem is stated
    unsure  the sentence alone is not enough to tell

Usage:
    python -m scripts.evolution_bench.strict_check              # write strict_check.csv (60 rows)
    python -m scripts.evolution_bench.strict_check --score      # after filling in `answer`
"""
import argparse
import csv
import math
import random

from sqlalchemy import select
from sqlalchemy.orm import aliased

from athena.core.models import EvoCitationContext, EvoPaper
from athena.database.db import SessionLocal
from athena.database.evolution import LIMITATION_LABELS
from scripts.evolution_bench.common import BENCH_DIR

SHEET = BENCH_DIR / "strict_check.csv"
COLUMNS = ["id", "citing", "cited", "section", "sentence", "answer", "notes"]
STRICT_ROWS, OTHER_ROWS = 40, 20
ANSWERS = {"yes", "no", "unsure"}


def _contexts() -> list[tuple[EvoCitationContext, str, str]]:
    citing, cited = aliased(EvoPaper), aliased(EvoPaper)
    with SessionLocal() as session:
        return session.execute(
            select(EvoCitationContext, citing.title, cited.title)
            .join(citing, EvoCitationContext.citing_id == citing.id)
            .join(cited, EvoCitationContext.cited_id == cited.id)
            .where(EvoCitationContext.label.isnot(None), EvoCitationContext.label != "unknown")
        ).all()


def is_strict(ctx: EvoCitationContext) -> bool:
    return ctx.label in LIMITATION_LABELS and ctx.attributed is True


def make():
    if SHEET.exists() and any(r["answer"].strip() for r in csv.DictReader(open(SHEET, encoding="utf-8"))):
        raise SystemExit(f"{SHEET} already has answers; delete it first to start over.")
    rows = _contexts()
    rng = random.Random(11)
    strict = [r for r in rows if is_strict(r[0])]
    other = [r for r in rows if not is_strict(r[0])]
    picks = rng.sample(strict, min(STRICT_ROWS, len(strict))) + rng.sample(other, min(OTHER_ROWS, len(other)))
    rng.shuffle(picks)
    with open(SHEET, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for ctx, citing_title, cited_title in picks:
            writer.writerow({"id": str(ctx.id), "citing": citing_title, "cited": cited_title,
                             "section": ctx.section_type or "", "sentence": ctx.marked or ctx.sentence,
                             "answer": "", "notes": ""})
    print(f"Wrote {len(picks)} rows ({len(strict)} strict links and {len(other)} other labelled sentences "
          f"available) to {SHEET}. Fill in `answer`, then run with --score.")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def score():
    answers = {r["id"]: r for r in csv.DictReader(open(SHEET, encoding="utf-8")) if r["answer"].strip()}
    if not answers:
        raise SystemExit(f"No answers in {SHEET} yet.")
    bad = [i for i, r in answers.items() if r["answer"].strip().lower() not in ANSWERS]
    if bad:
        raise SystemExit(f"Rows {bad} have answers outside {sorted(ANSWERS)}.")
    by_id = {str(ctx.id): ctx for ctx, _, _ in _contexts()}
    sure = {i: r["answer"].strip().lower() == "yes" for i, r in answers.items()
            if r["answer"].strip().lower() != "unsure" and i in by_id}
    tp = sum(1 for i, yes in sure.items() if yes and is_strict(by_id[i]))
    fp = sum(1 for i, yes in sure.items() if not yes and is_strict(by_id[i]))
    fn = sum(1 for i, yes in sure.items() if yes and not is_strict(by_id[i]))
    low, high = wilson(tp, tp + fp)
    print(f"Answered {len(answers)} rows ({len(answers) - len(sure)} unsure, left out).")
    print(f"Strict-link precision: {tp}/{tp + fp} = {tp / max(tp + fp, 1):.2f} (95% interval {low:.2f}-{high:.2f}); "
          f"target 0.80 -> {'met' if tp / max(tp + fp, 1) >= 0.8 else 'not met'}")
    print(f"Limitations in the non-strict sample: {fn} of {sum(1 for i in sure if not is_strict(by_id[i]))} "
          "(the filter missed these)")
    for i, yes in sure.items():
        if yes != is_strict(by_id[i]):
            ctx = by_id[i]
            print(f"\n{'missed' if yes else 'false positive'}: label={ctx.label} attributed={ctx.attributed}")
            print(f"    {(ctx.marked or ctx.sentence)[:240]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args()
    score() if args.score else make()


if __name__ == "__main__":
    main()
