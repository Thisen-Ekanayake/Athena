"""Idea and novelty check (E2): the verdict prompt asks only about what was found."""
from athena.evolution.ideas import verdict_prompt, verdict_schema

PAPERS = [{"title": "LoRA", "year": 2021, "abstract": "Low-rank updates."}]
THEMES = [{"label": "Quantization error", "topic_name": "PEFT", "open": False, "status": "quiet",
           "example": {"sentence": "Quantized adapters lose accuracy."}}]


def test_gaps_are_asked_about_only_when_some_matched():
    with_gaps = verdict_prompt("Train adapters in 2 bits.", PAPERS, THEMES)
    assert "Quantization error (PEFT; quiet)" in with_gaps and '"gaps": "..."' in with_gaps
    without = verdict_prompt("Train adapters in 2 bits.", PAPERS, [])
    assert "gaps" not in without and without.endswith('Return {"closest": "...", "new": "..."}.')


def test_verdict_schema_follows_the_prompt():
    assert verdict_schema(True)["required"] == ["closest", "new", "gaps"]
    assert verdict_schema(False)["required"] == ["closest", "new"]
    assert set(verdict_schema(False)["properties"]) == {"closest", "new"}


def test_papers_are_numbered_for_citation():
    text = verdict_prompt("idea " * 10, PAPERS * 2, [])
    assert "[1] LoRA (2021): Low-rank updates." in text and "[2] LoRA" in text
