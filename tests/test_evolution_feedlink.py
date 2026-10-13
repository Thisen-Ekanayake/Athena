"""Linking the feed to the maps (E5)."""
from uuid import uuid4

from athena.evolution.feedlink import arxiv_id_from_url, milestone_citations


def test_arxiv_ids_from_feed_urls():
    assert arxiv_id_from_url("http://arxiv.org/abs/2610.12375v1") == "2610.12375"
    assert arxiv_id_from_url("https://arxiv.org/pdf/1506.01497v3.pdf") == "1506.01497"
    assert arxiv_id_from_url("https://arxiv.org/abs/cs/0112017v1") == "cs/0112017"
    assert arxiv_id_from_url("https://openai.com/blog/x") is None
    assert arxiv_id_from_url(None) is None


def test_milestone_citations_count_every_map_but_list_milestones_only():
    lora, adapter, resnet = uuid4(), uuid4(), uuid4()
    membership = {
        lora: [{"topic": "peft", "topic_name": "PEFT", "title": "LoRA", "year": 2021, "named_method": "LoRA",
                "milestone": True}],
        adapter: [{"topic": "peft", "topic_name": "PEFT", "title": "Adapters", "year": 2019, "named_method": None,
                   "milestone": False}],
        resnet: [{"topic": "object-detection", "topic_name": "OD", "title": "ResNet", "year": 2015,
                  "named_method": "ResNet", "milestone": True},
                 {"topic": "peft", "topic_name": "PEFT", "title": "ResNet", "year": 2015, "named_method": "ResNet",
                  "milestone": False}],
    }
    cites, per_map = milestone_citations({lora, adapter, resnet, uuid4()}, membership)
    assert per_map == {"peft": 3, "object-detection": 1}
    assert [(c["topic"], c["title"]) for c in cites] == [("object-detection", "ResNet"), ("peft", "LoRA")]
    assert cites[1]["paper_id"] == str(lora)
