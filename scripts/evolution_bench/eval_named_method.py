"""
E9 — does the named-method feature (names citing papers use) pick better milestones?

Replays milestone selection from the stored build of each curated topic, so no
rebuild is needed: every paper's score is the sum of its stored parts, plus the
feature at weight w when ``evo_papers.cited_name`` has a name. Selection is
``athena.evolution.milestones.select_milestones`` with the topic's config, so
w = 0 reproduces the stored automatic picks (checked below).

For each topic and weight it reports how many of ``eval_milestones.REFERENCE``
are picked, and which milestones the weight adds and removes.

Rule agreed in the plan: adopt the smallest weight that picks more reference
milestones on at least one topic and fewer on none; otherwise keep 0. The
reference lists are mostly named methods, so the feature is favoured by them;
the swapped milestones are listed to be read by hand.

Usage:
    python -m scripts.evolution_bench.eval_named_method [--weights 0 0.05 0.1 0.15]
"""
import argparse

from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.evolution.milestones import PaperScore, select_milestones
from scripts.evolution_bench.eval_milestones import REFERENCE, _matches

TOPICS = ["object-detection", "peft", "diffusion-models", "retrieval-augmented-generation"]


def replay(slug: str, weights: list[float]) -> dict:
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        config = TopicConfig.from_dict(topic.config)
        rows = db._topic_rows(session, topic.id)
    base, named, years, titles, stored = {}, {}, {}, {}, set()
    for tp, p in rows:
        parts = tp.score_detail or {}
        # The stored total, not the sum of the rounded parts, so w = 0 reproduces the stored picks exactly.
        base[p.id] = (tp, (tp.milestone_score or 0.0) - parts.get("named_method", 0.0), parts.get("relevance", 0.0))
        named[p.id] = bool(isinstance(p.cited_name, dict) and p.cited_name.get("name"))
        years[p.id] = p.year
        titles[p.id] = p.title
        if tp.is_milestone_auto:
            stored.add(p.id)
    refs = {name: {pid for pid, t in titles.items() if any(_matches(r, t) for r in ref_titles)}
            for name, ref_titles in REFERENCE[slug].items()}
    out = {"named_candidates": sum(named.values()), "stored_milestones": len(stored), "weights": {}}
    picks_at = {}
    for w in weights:
        scores = {pid: PaperScore(kind=tp.kind, named_method=None, in_degree=tp.in_degree, out_degree=tp.out_degree,
                                  pagerank=tp.pagerank, citation_score=tp.citation_percentile,
                                  specificity=tp.specificity, relevance=rel, on_main_path=tp.on_main_path,
                                  milestone_score=round(total + w * named[pid], 4))
                  for pid, (tp, total, rel) in base.items()}
        picked = select_milestones(scores, years, config)
        picks_at[w] = picked
        out["weights"][w] = {"milestones": len(picked), "reference_total": len(refs),
                             "reference_picked": sum(bool(ids & picked) for ids in refs.values())}
    zero = picks_at.get(0.0)
    out["replay_matches_stored"] = zero == stored if zero is not None else None
    for w, picked in picks_at.items():
        if w and zero is not None:
            out["weights"][w]["added"] = sorted(f"{years[p]} {titles[p][:60]}" for p in picked - zero)
            out["weights"][w]["removed"] = sorted(f"{years[p]} {titles[p][:60]}" for p in zero - picked)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", type=float, nargs="+", default=[0.0, 0.05, 0.1, 0.15])
    ap.add_argument("slugs", nargs="*", default=TOPICS)
    args = ap.parse_args()
    for slug in args.slugs:
        r = replay(slug, args.weights)
        print(f"\n{slug}: {r['named_candidates']} papers named, {r['stored_milestones']} stored milestones, "
              f"replay at w=0 matches stored picks: {r['replay_matches_stored']}")
        for w, v in r["weights"].items():
            print(f"  w={w:<5} milestones={v['milestones']:3d}  "
                  f"reference picked {v['reference_picked']}/{v['reference_total']}")
            for label in ("added", "removed"):
                for t in v.get(label, []):
                    print(f"      {label[0]} {t}")


if __name__ == "__main__":
    main()
