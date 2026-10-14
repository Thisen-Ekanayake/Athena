"""
Literature reviews (ROADMAP S1), written in the background section by section and saved per user.

A **map** review is grounded in a built map:

1. The outline comes from the map, with no model call: its eras and their milestones (How the field developed),
   the named methods and top method papers (Main approaches compared), its gap themes with their status (Open
   problems) and its reading path (Where to start reading).
2. Evidence is gathered for every section before anything is written, so the model server swaps the embedding
   model for the chat model once: each paper's abstract, plus passages from the papers' own text where it was read
   (Ask a map's retrieval, limited to the section's papers), plus the gap sentences papers wrote. One registry
   numbers every paper once across the review.
3. Each section is one chat call that sees only its own sources and must cite them as [n]; the overview is written
   last from the finished sections. Where to start reading is put together from the reading path and its notes,
   without the model.
4. Citations to numbers a section was not given are removed. All citations are then renumbered by first
   appearance, and the reference list holds only the papers cited.

An **abstracts** review is the fallback when no map matches the query: one call over the search results'
abstracts (the library, Semantic Scholar and arXiv), checked and referenced the same way, and labelled as such.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from loguru import logger
from sqlalchemy import select

MAX_ERAS = 5
ERA_MILESTONES = 5
APPROACHES = 8
GAP_THEMES = 6
READING_STEPS = 8
PASSAGES = 8                 # full-text passages per section
ABSTRACT_CHARS = 1100
PASSAGE_CHARS = 900
SECTION_TOKENS = 700
OVERVIEW_TOKENS = 450
ABSTRACTS_TOKENS = 1300
ABSTRACT_PAPERS = 15
LIBRARY_PAPERS = 8           # of those, at most this many from the library, so the live sources get a say
MIN_ABSTRACT_PAPERS = 5      # fewer and the review would be about whatever happened to match
STALE_MINUTES = 15           # a running review with no progress for this long has lost its worker

# The second sentence came from the first live review: the 9B called Lester et al.'s prompt tuning "Prefix-tuning",
# because its abstract mentions prefix tuning, while citing Lester.
SYSTEM = ("You write sections of a literature review for researchers who are new to a field. Use only the numbered "
          "sources you are given. Cite every claim with the number of its source in square brackets, like [3] or "
          "[2, 5]. Never cite a number that is not listed, and never invent papers, results or figures. Call each "
          "paper by the name or title in its source's label, and credit a method only to the source that introduces "
          "it, not to one that merely mentions it. Write plain, precise prose without headings, unless the task asks "
          "for them.")
STATUS_WORDS = {"persisting": "persisting: papers keep raising it", "new": "new: raised only recently",
                "addressed": "addressed: later papers take it on", "quiet": "quiet: no longer raised"}
CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")


# ── sources and citations ────────────────────────────────────────────


@dataclass
class Paper:
    key: str
    title: str
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    name: str | None = None   # what citing papers call it ("LoRA")

    def label(self) -> str:
        name = f"{self.name}: " if self.name and self.name.lower() not in self.title.lower() else ""
        return f"{name}{self.title} ({self.year or 'n.d.'})"


class Registry:
    """Numbers each paper once across the whole review, in the order evidence is gathered."""

    def __init__(self):
        self.papers: dict[int, Paper] = {}
        self._by_key: dict[str, int] = {}

    def number(self, paper: Paper) -> int:
        if paper.key not in self._by_key:
            n = len(self.papers) + 1
            self._by_key[paper.key] = n
            self.papers[n] = paper
        return self._by_key[paper.key]


def _numbers(group: str) -> list[int]:
    out = []
    for part in re.split(r"\s*,\s*", group):
        if m := re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part):
            a, b = int(m.group(1)), int(m.group(2))
            out += list(range(a, b + 1)) if 0 < b - a < 20 else [a, b]
        elif part.strip().isdigit():
            out.append(int(part))
    return out


def check_citations(text: str, allowed: set[int]) -> tuple[str, int]:
    """Remove citations to numbers outside ``allowed``. Returns the text and how many were removed."""
    removed = 0

    def fix(m: re.Match) -> str:
        nonlocal removed
        nums = _numbers(m.group(1))
        keep = [n for n in dict.fromkeys(nums) if n in allowed]
        removed += len(nums) - len(keep)
        return f"[{', '.join(map(str, keep))}]" if keep else ""

    text = CITATION.sub(fix, text)
    return re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", text)), removed


def renumber(texts: list[str]) -> tuple[list[str], dict[int, int]]:
    """Renumber citations across ``texts`` by first appearance. Returns the texts and {old: new}."""
    mapping: dict[int, int] = {}
    for text in texts:
        for m in CITATION.finditer(text):
            for n in _numbers(m.group(1)):
                mapping.setdefault(n, len(mapping) + 1)

    def fix(m: re.Match) -> str:
        nums = sorted(dict.fromkeys(mapping[n] for n in _numbers(m.group(1)) if n in mapping))
        return f"[{', '.join(map(str, nums))}]"

    return [CITATION.sub(fix, t) for t in texts], mapping


def reference(n: int, p: Paper) -> str:
    authors = p.authors[:3]
    names = ", ".join(authors) + (" et al." if len(p.authors) > 3 else "") if authors else ""
    link = p.url or (f"https://doi.org/{p.doi}" if p.doi else "")
    bits = [f"{names} ({p.year or 'n.d.'})." if names else f"({p.year or 'n.d.'}).", f"*{p.title}*."]
    if p.venue:
        bits.append(f"{p.venue}.")
    if link:
        bits.append(link)
    return f"[{n}] " + " ".join(bits)


# ── the outline (map reviews) ────────────────────────────────────────


@dataclass
class Section:
    key: str
    title: str
    level: int = 2
    task: str = ""                    # what the model is asked to write
    evidence: list[tuple[int, str, str]] = field(default_factory=list)   # (n, label, text)
    papers: list[UUID] = field(default_factory=list)                     # whose passages to fetch
    question: str = ""                                                   # what to fetch them for
    passage_sections: list[str] | None = None
    markdown: str = ""
    by_model: bool = True


def _evo_paper(p, name: str | None = None) -> Paper:
    from athena.database.evolution import _paper_url
    return Paper(key=f"evo:{p.id}", title=p.title, year=p.year, authors=list(p.authors or []), venue=p.venue,
                 doi=p.doi, arxiv_id=p.arxiv_id, url=_paper_url(p), name=name)


def outline(session, topic, registry: Registry) -> list[Section]:
    """The review's sections for a built map, with each paper's abstract as first evidence."""
    from athena.database import evolution as db

    rows = db._topic_rows(session, topic.id)
    eras = db.topic_eras(topic, rows)
    timeline = db.topic_timeline(session, topic)
    milestones = [p for year in timeline["years"] for p in year["papers"]]
    papers = {p.id: p for _, p in rows}

    def cite(node: dict) -> int:
        return registry.number(_evo_paper(papers[UUID(node["id"])], node.get("named_method")))

    def abstract(node: dict) -> tuple[int, str, str]:
        p = papers[UUID(node["id"])]
        return cite(node), _evo_paper(p, node.get("named_method")).label(), (p.abstract or "")[:ABSTRACT_CHARS]

    sections = [Section("overview", "Overview", task="overview"),
                Section("history", "How the field developed", by_model=False)]
    for start, end in eras[-MAX_ERAS:]:
        picks = sorted((m for m in milestones if m["year"] and start <= m["year"] <= end),
                       key=lambda m: -m["milestone_score"])[:ERA_MILESTONES]
        if not picks:
            continue
        names = ", ".join(m.get("named_method") or m["title"] for m in sorted(picks, key=lambda m: m["year"]))
        sections.append(Section(
            f"era-{start}", f"{start}–{end}" if start != end else str(start), level=3,
            task=(f"Section: how {topic.name} developed in {start}–{end}. Its milestones: {names}.\nWrite 2–3 "
                  "paragraphs (about 250 words): the problems these papers took on, what each milestone introduced, "
                  "and how it built on or departed from earlier work."),
            evidence=[abstract(m) for m in picks], papers=[UUID(m["id"]) for m in picks],
            question=f"What did {names} introduce, and how do they work?"))

    approach = [m for m in sorted(milestones, key=lambda m: -m["milestone_score"]) if m.get("named_method")]
    if len(approach) < APPROACHES:
        seen = {m["id"] for m in approach}
        approach += [m for m in sorted(milestones, key=lambda m: -m["milestone_score"]) if m["id"] not in seen]
    approach = approach[:APPROACHES]
    if approach:
        sections.append(Section(
            "approaches", "Main approaches compared",
            task=(f"Section: the main approaches to {topic.name}, compared. Write 3–4 paragraphs (about 350 words): "
                  "group the approaches into families, and say what each assumes, where it does well, and the "
                  "limitations its papers state."),
            evidence=[abstract(m) for m in approach], papers=[UUID(m["id"]) for m in approach],
            question=f"How do the main approaches to {topic.name} differ, and what are their limitations?",
            passage_sections=["method", "limitations"]))

    themes = db.topic_gaps(session, topic)["themes"][:GAP_THEMES]
    if themes:
        evidence = []
        for t in themes:
            years = f"{t['first_year']}–{t['last_year']}" if t.get("first_year") else "years unknown"
            for ex in t["examples"]:
                who = ex.get("stated_by") or ex.get("paper")
                if who and UUID(who["id"]) in papers:
                    n = cite(who)
                    evidence.append((n, f"open problem “{t['label']}” ({STATUS_WORDS.get(t['status'], t['status'])}; "
                                        f"raised {years}), as {_evo_paper(papers[UUID(who['id'])]).label()} puts it",
                                     ex["sentence"][:PASSAGE_CHARS]))
            for fix in t.get("fixed_by", [])[:2]:
                if UUID(fix["id"]) in papers:
                    p = papers[UUID(fix["id"])]
                    evidence.append((cite(fix), f"takes on “{t['label']}”: {_evo_paper(p).label()}",
                                     (p.abstract or "")[:ABSTRACT_CHARS // 2]))
        listed = "; ".join(f"{t['label']} ({t['status']})" for t in themes)
        sections.append(Section(
            "gaps", "Open problems",
            task=(f"Section: the open problems of {topic.name}. The themes and their status: {listed}.\nWrite about "
                  "300 words: for each theme, what the problem is, how long it has been raised, and whether later "
                  "papers take it on. Keep each theme's status as given; do not call a problem solved unless a "
                  "source says so."),
            evidence=evidence))

    path = db.reading_path(session, topic, None, READING_STEPS)
    steps = ([path["survey"]] if path["survey"] else []) + path["steps"]
    if steps:
        lines = []
        for i, step in enumerate(steps, start=1):
            n = cite(step)
            why = f": {step['why']}" if step.get("why") else ""
            lines.append(f"{i}. **{step.get('named_method') or step['title']}** ({step['year'] or 'n.d.'}){why} [{n}]")
        sections.append(Section("reading", "Where to start reading", markdown="\n".join(lines), by_model=False))
    return sections


def gather(session, topic, sections: list[Section], registry: Registry, retrieve=None) -> int:
    """Fetch passages from the papers' own text for each section. Returns how many were found."""
    from athena.core.models import EvoPaper
    from athena.evolution import ask
    retrieve = retrieve or ask.retrieve
    found = 0
    for section in sections:
        if not section.papers:
            continue
        try:
            hits = retrieve(session, topic, section.question, section.passage_sections, paper_ids=section.papers,
                            chunk_limit=PASSAGES, per_paper=2, with_abstracts=False)
        except ask.AskUnavailable as exc:  # no embedding model: the abstracts carry the section
            logger.warning(f"Review {topic.slug}: passages not fetched: {exc}")
            return found
        for hit in hits:
            paper = session.get(EvoPaper, UUID(hit.paper_id))
            if paper is None:
                continue
            n = registry.number(_evo_paper(paper, hit.named_method))
            where = ask.SECTION_LABELS.get(hit.section_type, "Body")
            section.evidence.append((n, f"{_evo_paper(paper, hit.named_method).label()}, {where}: {hit.heading}",
                                     hit.text[:PASSAGE_CHARS]))
            found += 1
    return found


# ── writing ──────────────────────────────────────────────────────────


Chat = Callable[[list[dict], int], tuple[str, int, int]]


def section_messages(topic_name: str, section: Section) -> list[dict]:
    listed = "\n\n".join(f"[{n}] {label}\n{text}" for n, label, text in section.evidence)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Field: {topic_name}\n\nSources:\n\n{listed}\n\n{section.task}\nCite each "
                                        "claim with its source number."}]


def overview_messages(topic_name: str, written: list[Section]) -> list[dict]:
    body = "\n\n".join(f"{s.title}\n{s.markdown}" for s in written if s.markdown)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Field: {topic_name}\n\nThe sections of the review so far:\n\n{body}\n\n"
                                        "Write the review's opening overview: 1–2 paragraphs (about 150 words) on how "
                                        "the field developed, its main approaches and what remains open. Use only "
                                        "claims made in the sections above, keeping their citation numbers."}]


def abstracts_messages(query: str, papers: list[tuple[int, Paper, str]]) -> list[dict]:
    listed = "\n\n".join(f"[{n}] {p.label()}\n{abstract}" for n, p, abstract in papers)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Topic: {query}\n\nSources (abstracts only):\n\n{listed}\n\nWrite a short "
                                        "literature review in Markdown with these sections, each a level-2 heading: "
                                        "## Overview, ## Main themes, ## Notable findings, ## Open questions. About "
                                        "600 words. Cite each claim with its source number."}]


def _clean(text: str) -> str:
    """The model's text without a thinking block or a heading it was not asked for."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    return re.sub(r"\A#+ [^\n]*\n+", "", text)


@dataclass
class Result:
    sections: list[dict]
    sources: list[dict]
    markdown: str
    removed: int


def finish(title: str, preface: str, sections: list[Section], registry: Registry) -> Result:
    """Renumber the citations, build the references and the whole Markdown."""
    texts, mapping = renumber([s.markdown for s in sections])
    for s, text in zip(sections, texts):
        s.markdown = text
    cited = sorted(mapping.items(), key=lambda kv: kv[1])
    sources = [{"n": new, "key": registry.papers[old].key, "title": registry.papers[old].title,
                "year": registry.papers[old].year, "authors": registry.papers[old].authors,
                "venue": registry.papers[old].venue, "doi": registry.papers[old].doi,
                "arxiv_id": registry.papers[old].arxiv_id, "url": registry.papers[old].url,
                "name": registry.papers[old].name} for old, new in cited if old in registry.papers]
    parts = [f"# {title}", f"*{preface}*"]
    for s in sections:
        parts.append(f"{'#' * s.level} {s.title}")
        if s.markdown:
            parts.append(s.markdown)
    parts.append("## References")
    parts += [reference(new, registry.papers[old]) for old, new in cited if old in registry.papers]
    return Result(sections=[{"key": s.key, "title": s.title, "level": s.level, "markdown": s.markdown}
                            for s in sections], sources=sources, markdown="\n\n".join(parts), removed=0)


def write_map_review(session, topic, chat: Chat, save: Callable[[dict], None], retrieve=None) -> Result:
    """Outline, evidence, one call per section, the overview, then citations checked and renumbered."""
    registry = Registry()
    sections = outline(session, topic, registry)
    writable = [s for s in sections if s.by_model and s.key != "overview"]
    total = len(writable) + 2
    save({"progress": {"step": 1, "of": total, "label": "Reading the papers"}})
    passages = gather(session, topic, sections, registry, retrieve)
    logger.info(f"Review {topic.slug}: {passages} passages for {len(writable)} sections")
    removed = 0
    for i, section in enumerate(writable, start=2):
        save({"progress": {"step": i, "of": total, "label": f"Writing {section.title}"}})
        text, *_ = chat(section_messages(topic.name, section), SECTION_TOKENS)
        section.markdown, dropped = check_citations(_clean(text), {n for n, _, _ in section.evidence})
        removed += dropped
        save({"sections": _partial(sections)})
    save({"progress": {"step": total, "of": total, "label": "Writing the overview"}})
    overview = sections[0]
    text, *_ = chat(overview_messages(topic.name, writable), OVERVIEW_TOKENS)
    allowed = {n for s in writable for m in CITATION.finditer(s.markdown) for n in _numbers(m.group(1))}
    overview.markdown, dropped = check_citations(_clean(text), allowed)
    removed += dropped
    built = topic.built_at.date().isoformat() if topic.built_at else "an earlier build"
    preface = (f"Written by AI from the research map “{topic.name}” (built {built}): its milestones, open problems "
               "and the papers' own text. Check claims against the papers before relying on them.")
    result = finish(f"{topic.name}: a literature review", preface, sections, registry)
    result.removed = removed
    if removed:
        logger.info(f"Review {topic.slug}: removed {removed} citations to sources a section was not given")
    return result


def write_abstracts_review(query: str, papers: list[dict], chat: Chat, save: Callable[[dict], None]) -> Result:
    """One call over search results' abstracts, checked and referenced like a map review."""
    registry = Registry()
    numbered = []
    for p in papers[:ABSTRACT_PAPERS]:
        if not p.get("abstract"):
            continue
        paper = Paper(key=f"search:{p.get('id') or p['title']}", title=p["title"], year=p.get("year"),
                      authors=list(p.get("authors") or []), url=p.get("url"))
        numbered.append((registry.number(paper), paper, p["abstract"][:ABSTRACT_CHARS]))
    save({"progress": {"step": 1, "of": 1, "label": "Writing from the abstracts"}})
    if len(numbered) < MIN_ABSTRACT_PAPERS:
        raise ValueError(f"Only {len(numbered)} papers with abstracts matched the query (Semantic Scholar may be "
                         "rate-limiting). Try again in a few minutes, use a broader query, or build a map of the "
                         "topic.")
    text, *_ = chat(abstracts_messages(query, numbered), ABSTRACTS_TOKENS)
    body, removed = check_citations(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip(),
                                    {n for n, _, _ in numbered})
    section = Section("review", "Review", level=2, markdown=re.sub(r"^#{1,2} ", "### ", body, flags=re.M))
    preface = (f"Written by AI from the abstracts of {len(numbered)} search results: no research map covers this "
               "query, so it does not read the papers' full text or trace their history. Check claims against the "
               "papers.")
    result = finish(f"{query}: a literature review", preface, [section], registry)
    result.removed = removed
    return result


def _partial(sections: list[Section]) -> list[dict]:
    return [{"key": s.key, "title": s.title, "level": s.level, "markdown": s.markdown} for s in sections]


# ── running a saved review ───────────────────────────────────────────


def model_chat(user_id, model_used: dict) -> Chat:
    """A chat call through athena.core.llm that records its usage against the user."""
    from athena.core import llm, usage
    model = llm.chat_model("lit_review")
    model_used["model"] = model

    def chat(messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
        resp = llm.chat_client().chat.completions.create(model=model, messages=messages, max_tokens=max_tokens,
                                                         temperature=0.2, extra_body=llm.chat_extra())
        tokens_in, tokens_out = usage.tokens_of(resp.usage)
        usage.add("lit_review", model, tokens_in, tokens_out, user_id=user_id)
        model_used["in"] = model_used.get("in", 0) + tokens_in
        model_used["out"] = model_used.get("out", 0) + tokens_out
        return resp.choices[0].message.content or "", tokens_in, tokens_out

    return chat


def search_papers(query: str) -> list[dict]:
    """Papers with abstracts for an abstracts review: up to LIBRARY_PAPERS from the library, then Semantic Scholar
    and arXiv. Only papers with an abstract count: the library's best matches are often blog posts without one, and
    letting them fill the list (as the research search's merge does) left a review with two sources."""
    from athena.search.arxiv_live import search_arxiv
    from athena.search.local import search_local
    from athena.search.merger import merge_results
    from athena.search.semantic_scholar import search_semantic_scholar
    library = [p for p in search_local(query, limit=20) if p.get("abstract")][:LIBRARY_PAPERS]
    live = [p for p in search_semantic_scholar(query, limit=15) + search_arxiv(query, limit=15)
            if p.get("abstract")]
    return merge_results(library, live, max_total=ABSTRACT_PAPERS)


def run(review_id, chat: Chat | None = None, retrieve=None, papers=None) -> dict:
    """Write a saved review, recording progress as it goes. Returns its status."""
    from athena.core.models import EvoTopic, LitReview
    from athena.database.db import SessionLocal

    with SessionLocal() as session:
        review = session.get(LitReview, UUID(str(review_id)))
        if review is None or review.status not in ("queued", "running"):
            return {"status": review.status if review else "missing"}
        used: dict = {}
        chat = chat or model_chat(review.user_id, used)

        def save(fields: dict) -> None:
            if "progress" in fields:
                fields["progress"] = fields["progress"] | {"at": datetime.now(timezone.utc).isoformat()}
            for key, value in fields.items():
                setattr(review, key, value)
            session.commit()

        save({"status": "running", "progress": {"step": 0, "of": 1, "label": "Starting"}})
        try:
            if review.mode == "map":
                topic = session.get(EvoTopic, review.topic_id) if review.topic_id else None
                if topic is None or topic.built_at is None:
                    raise ValueError("The map is gone or not built")
                result = write_map_review(session, topic, chat, save, retrieve)
                review.built_at = topic.built_at
            else:
                result = write_abstracts_review(review.query or "", papers if papers is not None
                                                else search_papers(review.query or ""), chat, save)
        except Exception as exc:
            logger.warning(f"Review {review_id} failed: {exc}")
            session.rollback()
            save({"status": "failed", "error": str(exc)[:500], "finished_at": datetime.now(timezone.utc),
                  "model": used.get("model"), "input_tokens": used.get("in", 0),
                  "output_tokens": used.get("out", 0)})
            return {"status": "failed"}
        save({"status": "done", "sections": result.sections, "sources": result.sources, "markdown": result.markdown,
              "finished_at": datetime.now(timezone.utc), "model": used.get("model"),
              "input_tokens": used.get("in", 0), "output_tokens": used.get("out", 0),
              "progress": {"step": 1, "of": 1, "label": "Done"}})
        return {"status": "done", "citations_removed": result.removed}


def is_stale(review, now: datetime | None = None) -> bool:
    """A queued or running review whose worker stopped reporting."""
    if review.status not in ("queued", "running"):
        return False
    at = (review.progress or {}).get("at")
    last = datetime.fromisoformat(at) if at else review.created_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - last).total_seconds() > STALE_MINUTES * 60


def active(session, user_id) -> object | None:
    """The user's review being written now, if any (a stale one does not count)."""
    from athena.core.models import LitReview
    for review in session.execute(select(LitReview).where(LitReview.user_id == user_id,
                                                          LitReview.status.in_(("queued", "running")))).scalars():
        if not is_stale(review):
            return review
    return None
