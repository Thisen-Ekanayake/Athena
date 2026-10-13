"""Ask a map (E3): the prompt numbers the sources and marks abstracts."""
from athena.evolution.ask import SECTIONS, Source, messages


def source(n, abstract_only=False, section="method"):
    return Source(n=n, paper_id=f"p{n}", title=f"Paper {n}", year=2020 + n, named_method=None,
                  section_type="abstract" if abstract_only else section,
                  heading="Abstract" if abstract_only else "3.1 Low-rank updates", text=f"Text of {n}.",
                  abstract_only=abstract_only, score=0.8)


def test_sources_are_numbered_and_abstracts_marked():
    chat = messages("PEFT", "Why no latency?", [source(1), source(2, abstract_only=True)], [])
    assert chat[0]["role"] == "system" and "[n]" in chat[0]["content"]
    prompt = chat[-1]["content"]
    assert "[1] Paper 1 (2021), Method: 3.1 Low-rank updates\nText of 1." in prompt
    assert "[2] Paper 2 (2022), abstract only\nText of 2." in prompt
    assert prompt.endswith("Question: Why no latency?")


def test_history_keeps_the_last_three_turns():
    history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(5)]
    chat = messages("PEFT", "next", [], history)
    assert [m["content"] for m in chat[1:-1]] == ["q2", "a2", "q3", "a3", "q4", "a4"]
    assert "(none found)" in chat[-1]["content"]


def test_public_sources_carry_an_excerpt_not_the_text():
    public = source(1).public()
    assert "text" not in public and public["excerpt"] == "Text of 1." and public["n"] == 1


def test_section_filters_cover_known_section_types():
    from athena.evolution.tei import SECTION_TYPES
    assert all(t in SECTION_TYPES for types in SECTIONS.values() for t in types)
