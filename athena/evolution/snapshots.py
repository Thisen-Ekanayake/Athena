"""
Snapshots of a map and what changed between them (ROADMAP E4).

A snapshot keeps a topic's milestones, gap themes and paper IDs after a build
or a refresh. Comparing it with the one before gives the changelog: milestones
added and dropped, papers added, gaps newly stated, gaps a later paper claims
to have solved, and gaps that faded out.

Gap themes are re-clustered on every GPU lane run, so their IDs change; a theme
is matched to an earlier one by the gap statements they share (gap statement
IDs are stable), with the Jaccard overlap of their members.

Pure functions; ``athena.database.evolution.take_snapshot`` feeds them.
"""
from __future__ import annotations

THEME_MATCH = 0.3   # Jaccard overlap of member statements for two themes to count as the same gap
OPEN = {"persisting", "new"}
TOP_NEW_PAPERS = 5


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def match_themes(before: list[dict], after: list[dict], threshold: float = THEME_MATCH) -> dict[int, int]:
    """Index in ``after`` -> index in ``before`` of the same theme; best overlaps paired first, one to one."""
    pairs = sorted(((jaccard(set(b["members"]), set(a["members"])), j, i)
                    for i, b in enumerate(before) for j, a in enumerate(after)), reverse=True)
    matched, used = {}, set()
    for score, j, i in pairs:
        if score < threshold:
            break
        if j not in matched and i not in used:
            matched[j] = i
            used.add(i)
    return matched


def _theme(t: dict) -> dict:
    return {k: t.get(k) for k in ("label", "status", "size", "first_year", "last_year")}


def diff(before: dict | None, after: dict, paper_info: dict[str, dict] | None = None) -> dict | None:
    """What changed from ``before`` to ``after`` (both snapshot dicts); None for the first snapshot.

    ``paper_info`` ({paper id: {title, year, score}}) names the best of the papers added.
    """
    if before is None:
        return None
    old_ms = {m["paper_id"]: m for m in before["milestones"]}
    new_ms = {m["paper_id"]: m for m in after["milestones"]}
    added_papers = set(after["paper_ids"]) - set(before["paper_ids"])
    removed_papers = set(before["paper_ids"]) - set(after["paper_ids"])
    matched = match_themes(before["themes"], after["themes"])
    new_gaps, solved, reopened, faded = [], [], [], []
    for j, theme in enumerate(after["themes"]):
        if j not in matched:
            if theme["status"] in OPEN:
                new_gaps.append(_theme(theme))
            continue
        old = before["themes"][matched[j]]
        if theme["status"] == "addressed" and old["status"] != "addressed":
            solved.append(_theme(theme) | {"was": old["status"]})
        elif theme["status"] in OPEN and old["status"] not in OPEN:
            reopened.append(_theme(theme) | {"was": old["status"]})
        elif theme["status"] == "quiet" and old["status"] in OPEN:
            faded.append(_theme(theme) | {"was": old["status"]})
    # Open themes with no successor: their statements now sit in other themes or none.
    faded += [_theme(t) | {"was": t["status"]} for i, t in enumerate(before["themes"])
              if i not in set(matched.values()) and t["status"] in OPEN]
    info = paper_info or {}
    top_new = [{"paper_id": pid, **{k: info[pid].get(k) for k in ("title", "year")}}
               for pid in sorted((p for p in added_papers if p in info), key=lambda p: -info[p].get("score", 0.0))
               [:TOP_NEW_PAPERS]]
    return {
        "new_milestones": [new_ms[p] for p in new_ms if p not in old_ms],
        "dropped_milestones": [old_ms[p] for p in old_ms if p not in new_ms],
        "papers_added": len(added_papers),
        "papers_removed": len(removed_papers),
        "top_new_papers": top_new,
        "new_gaps": new_gaps,
        "solved_gaps": solved,
        "reopened_gaps": reopened,
        "faded_gaps": faded,
    }


def is_empty(changes: dict | None) -> bool:
    return changes is not None and not any(changes[k] for k in (
        "new_milestones", "dropped_milestones", "papers_added", "papers_removed", "new_gaps", "solved_gaps",
        "reopened_gaps", "faded_gaps"))
