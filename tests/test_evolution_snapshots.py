"""Snapshots and changes (E4): themes are matched by shared statements, and changes named."""
from athena.evolution.snapshots import diff, is_empty, jaccard, match_themes


def theme(label, status, members, size=None):
    return {"label": label, "status": status, "size": size or len(members), "first_year": 2020, "last_year": 2024,
            "members": members}


def snap(milestones, themes, papers):
    return {"milestones": [{"paper_id": m, "title": m.upper(), "year": 2020} for m in milestones],
            "themes": themes, "paper_ids": papers}


def test_jaccard():
    assert jaccard({1, 2}, {2, 3}) == 1 / 3 and jaccard(set(), set()) == 0.0


def test_themes_match_one_to_one_by_shared_statements():
    before = [theme("Memory cost", "persisting", ["a", "b", "c", "d"]), theme("Latency", "new", ["x", "y"])]
    after = [theme("Memory of adapters", "persisting", ["a", "b", "c", "e"]), theme("Other", "new", ["q", "r"])]
    assert match_themes(before, after) == {0: 0}


def test_changes_name_milestones_papers_and_gaps():
    before = snap(["m1", "m2"], [theme("Memory", "persisting", ["a", "b", "c"]), theme("Latency", "new", ["x", "y"]),
                                 theme("Quiet one", "quiet", ["q1", "q2"])], ["m1", "m2", "p1"])
    after = snap(["m1", "m3"], [theme("Memory", "addressed", ["a", "b", "c", "d"]),
                                theme("Data leakage", "new", ["n1", "n2", "n3"]),
                                theme("Quiet one", "persisting", ["q1", "q2"])], ["m1", "m3", "p1", "p2", "p3"])
    info = {"m3": {"title": "M3", "year": 2025, "score": 0.9}, "p2": {"title": "P2", "year": 2025, "score": 0.4},
            "p3": {"title": "P3", "year": 2025, "score": 0.6}}
    c = diff(before, after, info)
    assert [m["paper_id"] for m in c["new_milestones"]] == ["m3"]
    assert [m["paper_id"] for m in c["dropped_milestones"]] == ["m2"]
    assert (c["papers_added"], c["papers_removed"]) == (3, 1)
    assert [p["paper_id"] for p in c["top_new_papers"]] == ["m3", "p3", "p2"]
    assert [t["label"] for t in c["new_gaps"]] == ["Data leakage"]
    assert c["solved_gaps"][0]["label"] == "Memory" and c["solved_gaps"][0]["was"] == "persisting"
    assert c["reopened_gaps"][0]["label"] == "Quiet one"
    assert [t["label"] for t in c["faded_gaps"]] == ["Latency"]  # open before, no successor now


def test_an_open_theme_gone_quiet_has_faded():
    before = snap([], [theme("Speed", "persisting", ["a", "b"])], [])
    after = snap([], [theme("Speed", "quiet", ["a", "b"])], [])
    assert diff(before, after)["faded_gaps"][0]["was"] == "persisting"


def test_first_snapshot_has_no_changes_and_identical_ones_are_empty():
    s = snap(["m1"], [theme("T", "new", ["a"])], ["m1"])
    assert diff(None, s) is None
    assert is_empty(diff(s, s)) and not is_empty(None)
