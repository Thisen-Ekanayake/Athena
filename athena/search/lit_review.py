"""LLM-driven literature review synthesis."""
from __future__ import annotations

from loguru import logger
from openai import OpenAI

from athena.core.config_store import get_setting

MODEL = "gpt-4o"
MAX_TOKENS = 2000
MAX_PAPERS_ON_OVERFLOW = 12
PROMPT_OVERFLOW_CHARS = 300_000

SYSTEM_PROMPT = (
    "You are an expert academic research assistant. Your task is to write a "
    "structured literature review based only on the provided paper abstracts. "
    "Do not invent, hallucinate, or reference any paper not in the provided list."
)


def _build_user_prompt(topic: str, papers: list[dict]) -> str:
    lines = [f"Topic: {topic}", "", "Papers:"]
    for idx, paper in enumerate(papers, start=1):
        title = paper.get("title") or "(untitled)"
        abstract = paper.get("abstract") or ""
        lines.append(f"[{idx}] Title: {title}")
        lines.append(f"    Abstract: {abstract}")
    lines.append("")
    lines.append("Write a literature review with the following sections:")
    lines.append("1. Overview — summarise the state of research on this topic")
    lines.append("2. Key Themes — identify 3–5 recurring themes across the papers")
    lines.append(
        "3. Notable Findings — highlight the most significant results, "
        "citing paper numbers e.g. [1], [3]"
    )
    lines.append("4. Research Gaps — what questions remain unanswered?")
    lines.append("5. Methodological Trends — what approaches are most common?")
    return "\n".join(lines)


def generate_lit_review(topic: str, papers: list[dict]) -> str:
    """Generate a structured literature review from the provided papers."""
    if not papers:
        return ""

    trimmed = papers
    if len(str(papers)) > PROMPT_OVERFLOW_CHARS:
        logger.info(
            "lit_review: prompt overflow detected, trimming to top "
            f"{MAX_PAPERS_ON_OVERFLOW} papers"
        )
        trimmed = papers[:MAX_PAPERS_ON_OVERFLOW]

    user_prompt = _build_user_prompt(topic, trimmed)

    client = OpenAI(api_key=get_setting("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""
