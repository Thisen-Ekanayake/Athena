"""Named method as a milestone-score feature (E9): names from citing sentences, and their weight."""
from athena.evolution.config import MilestoneWeights, TopicConfig
from athena.evolution.corpus import Corpus
from athena.evolution.method_names import name_from_contexts
from athena.evolution.milestones import score_topic
from tests.test_evolution_graph import _paper

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


def test_the_feature_counts_only_at_a_positive_weight():
    papers = {pid: _paper(pid, 2015, 100) for pid in ("named", "plain")}
    named = {"named": "Det-X"}
    off = score_topic(Corpus(papers=papers, edges=set()), TopicConfig(keywords=["detect"]), cited_names=named)
    assert off.papers["named"].milestone_score == off.papers["plain"].milestone_score
    on = TopicConfig(keywords=["detect"], weights=MilestoneWeights(named_method=0.1))
    scores = score_topic(Corpus(papers=papers, edges=set()), on, cited_names=named)
    assert scores.papers["named"].detail["named_method"] == 0.1 and scores.papers["plain"].detail["named_method"] == 0
