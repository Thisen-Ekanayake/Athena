"""
Phase 0 — parse the test papers with GROBID and report what came out.

Saves one TEI XML file per paper to out/tei/ and prints, per paper, the
section headings with their rule-assigned type and the citing sentences
found for each known citing → cited pair.

Usage:
    docker run -d --name athena-grobid -p 8070:8070 grobid/grobid:0.9.1-crf
    python -m scripts.evolution_bench.grobid_parse            # parse papers missing a TEI file
    python -m scripts.evolution_bench.grobid_parse --force    # re-parse everything
"""
import argparse
import time
from collections import Counter

import httpx
from loguru import logger

from scripts.evolution_bench.common import (
    GROBID_URL, KNOWN_PAIRS, PAPERS, TEI_DIR, load_parsed, pdf_path, resolve_refs,
)


def parse_pdf(client: httpx.Client, pdf) -> str:
    with open(pdf, "rb") as f:
        resp = client.post(
            f"{GROBID_URL}/api/processFulltextDocument",
            files={"input": (pdf.name, f, "application/pdf")},
            # Consolidation calls CrossRef; keep the benchmark local and fast.
            data={"segmentSentences": "1", "consolidateHeader": "0", "consolidateCitations": "0"},
        )
    resp.raise_for_status()
    return resp.text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-parse papers that already have a TEI file")
    args = ap.parse_args()

    TEI_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300.0) as client:
        client.get(f"{GROBID_URL}/api/isalive").raise_for_status()
        for paper in PAPERS:
            target = TEI_DIR / f"{paper.key}.tei.xml"
            if target.exists() and not args.force:
                continue
            pdf = pdf_path(paper)
            start = time.time()
            target.write_text(parse_pdf(client, pdf), encoding="utf-8")
            logger.info(f"{paper.key:12s} parsed in {time.time() - start:5.1f}s")

    parsed = load_parsed()
    print("\n=== Sections per paper (rule type; '<' = inherited from parent section) ===")
    for paper in PAPERS:
        pp = parsed.get(paper.key)
        if pp is None:
            print(f"\n{paper.key}: no TEI")
            continue
        title_ok = "ok" if pp.tei_title.lower()[:20] == paper.title.lower()[:20] else f"MISMATCH: {pp.tei_title!r}"
        n_sent = sum(len(s.sentences) for s in pp.sections) + len(pp.abstract)
        print(f"\n{paper.key} ({paper.year}) title {title_ok} · {len(pp.sections)} sections · "
              f"{n_sent} sentences · {len(pp.bib)} references · "
              f"{pp.fallback_links} citations linked by author-year fallback")
        for s in pp.sections:
            marker = " " if s.rule_type else "<"
            print(f"  {marker} {s.section_type:12s} {(s.number or ''):6s} {s.heading[:70]}")

    print("\n=== Citing sentences for known pairs ===")
    missing = []
    for citing, cited in KNOWN_PAIRS:
        pp = parsed.get(citing)
        if pp is None:
            missing.append((citing, cited))
            continue
        resolved = resolve_refs(pp)
        ids = {xml_id for xml_id, key in resolved.items() if key == cited}
        hits = [s for sec in pp.sections for s in sec.sentences if ids & set(s.refs)]
        print(f"  {citing:12s} -> {cited:12s} bib entries: {len(ids)}  citing sentences: {len(hits)}")
        if not hits:
            missing.append((citing, cited))
    if missing:
        print(f"\nPairs with no citing sentence found: {missing}")

    types = Counter(s.section_type for pp in parsed.values() for s in pp.sections)
    unmatched = sum(1 for pp in parsed.values() for s in pp.sections if s.rule_type is None)
    total = sum(types.values())
    print(f"\nSection types: {dict(types)}")
    print(f"Headings no rule matched (inherited or 'other'): {unmatched}/{total}")


if __name__ == "__main__":
    main()
