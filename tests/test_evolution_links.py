"""Links between maps (E7): the cross-map pass keeps other maps' method papers only."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import numpy as np

from athena.evolution import gpu

OWN, OTHER = str(uuid4()), str(uuid4())


def hit(paper_id, score, chunk=None):
    return SimpleNamespace(id=str(chunk or uuid4()), score=score, payload={"paper_id": str(paper_id)})


def test_cross_links_keep_later_method_papers_of_other_maps():
    gap = SimpleNamespace(id=uuid4(), paper_id=uuid4(), source_paper_id=uuid4(), sentence="It is slow.")
    same_map, survey, method_a, method_b, low = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    places = {gap.paper_id: {OWN: "method"}, same_map: {OWN: "method", OTHER: "method"}, survey: {OTHER: "survey"},
              method_a: {OTHER: "method"}, method_b: {OTHER: "method"}, low: {OTHER: "method"}}
    hits = [hit(same_map, 0.9), hit(survey, 0.85), hit(method_a, 0.8), hit(method_a, 0.79), hit(method_b, 0.7),
            hit(low, 0.2)]
    saved = {}

    def kinds(session, ids):
        return {i: places[i] for i in ids if i in places}

    with patch.object(gpu.db, "pending_cross", side_effect=[[(gap, 2019)], []]), \
            patch.object(gpu.db, "paper_topic_kinds", side_effect=kinds), \
            patch.object(gpu.db, "save_cross_links", side_effect=lambda s, gid, links: saved.setdefault(gid, links)), \
            patch.object(gpu.db, "mark_gaps") as mark, \
            patch.object(gpu, "_fit", side_effect=lambda http, url, text: (text, False)), \
            patch.object(gpu, "_embed", return_value=np.zeros((1, 4))), \
            patch.object(gpu.vectors, "later_chunks_anywhere", return_value=hits) as search:
        assert gpu._cross_links(None, "http://x", None) == 2
    links = saved[gap.id]
    assert [link["paper_id"] for link in links] == [method_a, method_b]  # best chunk per paper, nearest first
    assert links[0]["score"] == 0.8
    assert search.call_args.args[1] == 2019 and str(gap.paper_id) in search.call_args.args[2]
    assert mark.call_args.args[1:] == ([gap.id], "cross_checked_at")


def test_a_gap_whose_paper_is_in_no_map_gets_no_links():
    gap = SimpleNamespace(id=uuid4(), paper_id=uuid4(), source_paper_id=uuid4(), sentence="x")
    saved = {}
    with patch.object(gpu.db, "pending_cross", side_effect=[[(gap, None)], []]), \
            patch.object(gpu.db, "paper_topic_kinds", return_value={}), \
            patch.object(gpu.db, "save_cross_links", side_effect=lambda s, gid, links: saved.setdefault(gid, links)), \
            patch.object(gpu.db, "mark_gaps"), \
            patch.object(gpu, "_fit", side_effect=lambda http, url, text: (text, False)), \
            patch.object(gpu, "_embed", return_value=np.zeros((1, 4))), \
            patch.object(gpu.vectors, "later_chunks_anywhere") as search:
        gpu._cross_links(None, "http://x", None)
    assert saved[gap.id] == [] and not search.called
