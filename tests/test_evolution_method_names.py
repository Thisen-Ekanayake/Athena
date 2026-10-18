"""Named methods from citing sentences (E9, parked): which name, if any, citing papers use for a paper."""
from athena.evolution.method_names import name_from_contexts

TITLE = "LoRA: Low-Rank Adaptation of Large Language Models"


def test_a_name_most_single_citation_sentences_use():
    contexts = [(f"c{i}", [f"We fine-tune with LoRA [{i}] on all layers."]) for i in range(6)]
    contexts += [(f"m{i}", ["Adapters [3] and LoRA [4] both work."]) for i in range(40)]  # two markers: no evidence
    out = name_from_contexts(contexts, TITLE)
    assert out == {"name": "LoRA", "users": 6, "citers": 6}


def test_no_name_when_too_few_papers_use_one():
    contexts = [("a", ["LoRA [1] is used."]), ("b", ["LoRA [2] helps."])]
    contexts += [(f"x{i}", ["Hu et al. [5] show."]) for i in range(8)]
    assert name_from_contexts(contexts, TITLE)["name"] is None
