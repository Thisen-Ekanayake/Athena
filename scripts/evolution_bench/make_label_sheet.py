"""
Phase 0 — build labels.csv, the hand-labelled gold set for the benchmark.

Task A (~50 rows): is this sentence a research gap?
Task B (~50 rows): what does the citing sentence say about the cited paper? (cue-stratified)
Task C (~15 rows): is the rule-assigned section type right? (pre-filled)

Sentences are sampled deterministically from the parsed TEI files. The
``suggested`` column is only filled for Task C so it does not bias A and B.

Usage:
    python -m scripts.evolution_bench.make_label_sheet          # refuses to overwrite filled labels
    python -m scripts.evolution_bench.make_label_sheet --force
"""
import argparse
import csv
import random
import re

from scripts.evolution_bench.common import (
    KNOWN_PAIRS, KNOWN_TITLES, LABEL_COLUMNS, LABELS_PATH, PAPERS, load_parsed, read_labels, resolve_refs,
)

TASK_A_ROWS, TASK_B_ROWS, TASK_C_ROWS = 50, 50, 15
TASK_B_CUE_PER_PAIR, TASK_B_PLAIN_PER_PAIR = 2, 1
TASK_B_NEGATIVES = 4
GAP_SECTIONS = {"intro", "discussion", "limitations", "conclusion", "future_work"}
GAP_CUES = re.compile(
    r"\b(however|limitation|limited|fail|cannot|unable|remain|challeng|drawback|suffer|expensive|costly|slow"
    r"|bottleneck|future work|open (problem|question)|lack|difficult|inefficien|prohibitive|struggle)",
    re.IGNORECASE,
)
# Random citing sentences are mostly background (3 of 40 stated a limitation), so Task B
# over-samples sentences with contrast or criticism cues to get enough positives to measure.
CONTRAST_CUES = re.compile(
    r"\b(however|unlike|in contrast|contrary|whereas|but|although|suffer|slow|expensive|costly|inefficien|limit"
    r"|fail|cannot|unable|drawback|shallow|bottleneck|complex|inelegant|only|lack|difficult|problem|issue"
    r"|prohibitive|sub-?optimal|degrad|gap)",
    re.IGNORECASE,
)


def _usable(text: str) -> bool:
    words = len(text.split())
    return 8 <= words <= 80


def task_a(parsed, rng) -> list[dict]:
    """Two cue-word sentences and one plain sentence per paper, from gap-prone sections."""
    rows = []
    for paper in PAPERS:
        pp = parsed.get(paper.key)
        if pp is None:
            continue
        candidates = [("abstract", s) for s in pp.abstract]
        candidates += [(sec.heading, s) for sec in pp.sections if sec.section_type in GAP_SECTIONS
                       for s in sec.sentences]
        candidates = [(h, s) for h, s in candidates if _usable(s.text)]
        cue = [c for c in candidates if GAP_CUES.search(c[1].text)]
        plain = [c for c in candidates if not GAP_CUES.search(c[1].text)]
        picks = rng.sample(cue, min(2, len(cue))) + rng.sample(plain, min(1, len(plain)))
        rows += [{"task": "A", "paper": paper.key, "cited": "", "section": h, "sentence": s.text}
                 for h, s in picks]
    rng.shuffle(rows)
    return rows[:TASK_A_ROWS]


def task_b(parsed, rng) -> list[dict]:
    """Citing sentences for each known pair (cue-stratified), plus a few citing unrelated references."""
    rows, seen = [], set()
    for citing, cited in KNOWN_PAIRS:
        pp = parsed.get(citing)
        if pp is None:
            continue
        ids = {xml_id for xml_id, key in resolve_refs(pp).items() if key == cited}
        hits = [(sec.heading, s) for sec in pp.sections for s in sec.sentences
                if ids & set(s.refs) and _usable(s.text) and s.text not in seen]
        cue = [h for h in hits if CONTRAST_CUES.search(h[1].text)]
        plain = [h for h in hits if not CONTRAST_CUES.search(h[1].text)]
        picks = rng.sample(cue, min(TASK_B_CUE_PER_PAIR, len(cue)))
        want_plain = TASK_B_CUE_PER_PAIR + TASK_B_PLAIN_PER_PAIR - len(picks)
        picks += rng.sample(plain, min(want_plain, len(plain)))
        for heading, s in picks:
            seen.add(s.text)
            rows.append({"task": "B", "paper": citing, "cited": cited, "section": heading, "sentence": s.text})

    citing_keys = sorted({c for c, _ in KNOWN_PAIRS if c in parsed})
    negatives = []
    for key in citing_keys:
        pp = parsed[key]
        known_ids = set(resolve_refs(pp))
        for sec in pp.sections:
            for s in sec.sentences:
                other = [r for r in s.refs if r not in known_ids and r in pp.bib]
                if other and len(s.refs) == 1 and _usable(s.text) and s.text not in seen:
                    negatives.append({"task": "B", "paper": key, "cited": pp.bib[other[0]].title[:120],
                                      "section": sec.heading, "sentence": s.text})
    rows += rng.sample(negatives, min(TASK_B_NEGATIVES, len(negatives)))
    rng.shuffle(rows)
    return rows[:TASK_B_ROWS]


def task_c(parsed, rng) -> list[dict]:
    """Distinct headings, favouring ones the rules could not place on their own."""
    pool = []
    for paper in PAPERS:
        pp = parsed.get(paper.key)
        if pp is None:
            continue
        for sec in pp.sections:
            if sec.heading == "(untitled)":
                continue
            snippet = " ".join(" ".join(s.text for s in sec.sentences[:2]).split()[:30])
            pool.append({"task": "C", "paper": paper.key, "cited": "", "section": sec.heading,
                         "sentence": snippet, "suggested": sec.section_type, "label": sec.section_type,
                         "_inherited": sec.rule_type is None})
    hard = [r for r in pool if r["_inherited"]]
    easy = [r for r in pool if not r["_inherited"]]
    n_hard = min(len(hard), TASK_C_ROWS // 2 + 1)
    rows = rng.sample(hard, n_hard) + rng.sample(easy, min(len(easy), TASK_C_ROWS - n_hard))
    for r in rows:
        r.pop("_inherited")
    rng.shuffle(rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite labels.csv even if labels are filled in")
    args = ap.parse_args()

    if LABELS_PATH.exists() and not args.force:
        filled = [r for r in read_labels() if r["task"] in ("A", "B") and r["label"].strip()]
        if filled:
            raise SystemExit(f"{LABELS_PATH} already has {len(filled)} labels; pass --force to overwrite.")

    parsed = load_parsed()
    if not parsed:
        raise SystemExit("No TEI files found. Run grobid_parse first.")
    rng = random.Random(42)
    rows = task_a(parsed, rng) + task_b(parsed, rng) + task_c(parsed, rng)

    with open(LABELS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        for i, row in enumerate(rows, start=1):
            prefix = row["task"].lower()
            writer.writerow({col: "" for col in LABEL_COLUMNS} | row | {"id": f"{prefix}{i:03d}"})

    counts = {t: sum(1 for r in rows if r["task"] == t) for t in "ABC"}
    print(f"Wrote {len(rows)} rows to {LABELS_PATH}: {counts}")
    print(f"Cited titles for Task B: {', '.join(sorted({r['cited'] for r in rows if r['cited'] in KNOWN_TITLES}))}")
    print("""
How to label (fill the `label` column; use `notes` when unsure):
  Task A  gap                   states a limitation, an unsolved problem, or something existing methods
                                (or this paper) cannot do
          not_gap               anything else, including claims about the paper's own results
  Task B  addresses_limitation  the cited work has a problem and the citing paper claims to fix or improve on it
          criticises            states a problem or limitation of the cited work, with no fix claimed in the
                                same sentence
          extends_or_uses       builds on or uses the cited method, data or code without claiming to fix a flaw
          compares              reports results against the cited work as a baseline
          background            mentions the cited work as context
          (judge only what the sentence says about the paper in the `cited` column)
  Task C  check the pre-filled type; change it if wrong. Allowed: intro, related_work, method, results,
          discussion, limitations, conclusion, future_work, other
""")


if __name__ == "__main__":
    main()
