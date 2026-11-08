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

An **abstracts** review is the fallback when no map covers the query: one call over the abstracts of the papers
``athena.evolution.review_search`` finds (planned searches, ranked by relevance to the question, one snowball hop,
a relevance floor), checked and referenced the same way, and labelled as such. With too few relevant papers it says
so, lists what it did find and suggests building a map, rather than writing a full review from off-topic papers.

A review asked as a question keeps it: the question is its title, a map review gets a section answering it from
the map's papers, and both say which parts of the question nothing they read covers.

Every written section then goes through ``athena.evolution.verify``: citations whose source does not support the
sentence are removed (feedback 2026-11-07).
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
THIN_TOKENS = 500
QUESTION_TOKENS = 600
ABSTRACT_PAPERS = 20
MIN_ABSTRACT_PAPERS = 5      # fewer relevant papers and the review says so instead of writing the full template
QUESTION_PASSAGES = 10       # passages and abstracts for a map review's answer to the question
TITLE_WORDS = 12             # a longer question is shortened for the title
MAX_PUBLISHED_GAP = 3        # years between a first-seen date and the record's own, beyond which the record is wrong
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
MOTIVATION_SECTIONS = {"intro", "abstract", "related_work"}   # as athena.database.evolution.gaps


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
    published_year: int | None = None   # the record's own year, when the map dates the paper earlier (first seen)

    def label(self) -> str:
        name = f"{self.name}: " if self.name and self.name.lower() not in self.title.lower() else ""
        when = f"{self.year}; published {self.published_year}" if self.published_year else self.year or "n.d."
        return f"{name}{self.title} ({when})"


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
    year = p.published_year or p.year or "n.d."   # a reference gives the year it was published
    bits = [f"{names} ({year})." if names else f"({year}).", f"*{p.title}*."]
    if p.venue:
        bits.append(f"{p.venue}.")
    if link:
        bits.append(link)
    return f"[{n}] " + " ".join(bits)


def short_title(query: str) -> str:
    """A question as a title: whole when short, else its first clause, else its first words."""
    query = " ".join(query.split())
    if len(query.split()) <= TITLE_WORDS:
        return query
    head = re.split(r"[:;(?]", query)[0].strip(" ,.")
    if 2 <= len(head.split()) <= TITLE_WORDS:
        return head
    return " ".join(query.split()[:TITLE_WORDS - 2]).rstrip(",;:") + "…"


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
                 doi=p.doi, arxiv_id=p.arxiv_id, url=_paper_url(p), name=name, published_year=published_year(p))


def published_year(p) -> int | None:
    """The year to cite a map paper by, when the map dates it earlier than its record.

    A map dates papers by first appearance: a year with no arXiv ID can be pulled back to when citers first cite it
    (``corpus._repair_year``), so a TALLIP article of 2021 shows as 2019. A reference gives the record's year then,
    unless the two are far apart: OpenAlex dated Kaldi (2011) from a repository copy of 2024.
    """
    year, record = getattr(p, "year", None), getattr(p, "openalex_year", None)
    if getattr(p, "year_source", None) == "citers" and year and record and 0 < record - year <= MAX_PUBLISHED_GAP:
        return record
    return None


def outline(session, topic, registry: Registry) -> list[Section]:
    """The review's sections for a built map, with each paper's abstract as first evidence."""
    from athena.database import evolution as db

    rows = db._topic_rows(session, topic.id)
    eras = db.topic_eras(topic, rows)
    timeline = db.topic_timeline(session, topic)
    milestones = [p for year in timeline["years"] for p in year["papers"]]
    papers = {p.id: p for _, p in rows}
    # An era without milestones (recent years, whose papers have few citers yet) is told from its best on-topic
    # papers, so the history reaches the present (feedback 2026-11-07: a map's milestones stopped at 2022).
    ranked = sorted(((tp, p) for tp, p in rows if (getattr(tp, "score_detail", None) or {}).get("relevance", 0) > 0
                     and getattr(tp, "kind", "method") in ("method", "dataset")),
                    key=lambda r: -(getattr(r[0], "milestone_score", 0) or 0))

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
        kind = "milestones"
        if not picks:
            picks = [{"id": str(p.id), "title": p.title, "year": p.year,
                      "named_method": getattr(tp, "named_method", None),
                      "milestone_score": getattr(tp, "milestone_score", 0) or 0}
                     for tp, p in ranked if p.year and start <= p.year <= end][:ERA_MILESTONES]
            kind = "most important papers (none is a milestone yet)"
        if not picks:
            continue
        picks.sort(key=lambda m: (m["year"], -m["milestone_score"]))   # told in order of year
        names = ", ".join(f"{m.get('named_method') or m['title']} ({m['year']})" for m in picks)
        sections.append(Section(
            f"era-{start}", f"{start}–{end}" if start != end else str(start), level=3,
            task=(f"Section: how {topic.name} developed in {start}–{end}. Its {kind}, in order of year: {names}.\n"
                  "Write 2–3 paragraphs (about 250 words): the problems these papers took on, what each introduced, "
                  "and how it built on or departed from earlier work. Keep to the order of years: a paper can build "
                  "only on work from its own year or earlier, never on a later one."),
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
                    where = (", in its introduction, as motivation" if ex.get("section_type") in MOTIVATION_SECTIONS
                             else f", in its {ex['section_type'].replace('_', ' ')} section"
                             if ex.get("section_type") not in (None, "other") else "")
                    evidence.append((n, f"open problem “{t['label']}” ({STATUS_WORDS.get(t['status'], t['status'])}; "
                                        f"raised {years}), as {_evo_paper(papers[UUID(who['id'])]).label()} puts it"
                                        f"{where}", ex["sentence"][:PASSAGE_CHARS]))
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
                  "source says so. A problem a paper raises only in its introduction, to motivate itself, is weaker "
                  "evidence than one stated as a limitation: say so when a theme rests on such statements."),
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


def overview_messages(topic_name: str, written: list[Section], query: str | None = None) -> list[dict]:
    body = "\n\n".join(f"{s.title}\n{s.markdown}" for s in written if s.markdown)
    asked = (f"The reader asked: {query}\nOpen with what the review found on that question, including what the map "
             "does not cover, then " if query else "Cover ")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Field: {topic_name}\n\nThe sections of the review so far:\n\n{body}\n\n"
                                        "Write the review's opening overview: 1–2 paragraphs (about 150 words). "
                                        f"{asked}how the field developed, its main approaches and what remains open. "
                                        "Use only claims made in the sections above, keeping their citation "
                                        "numbers."}]


def question_messages(topic_name: str, query: str, section: Section, uncovered: list[str]) -> list[dict]:
    listed = "\n\n".join(f"[{n}] {label}\n{text}" for n, label, text in section.evidence)
    missing = (f"\nParts of the question none of the map's papers cover: {'; '.join(uncovered)}. Say so plainly, "
               "and do not fill them in from general knowledge." if uncovered else "")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Field: {topic_name}\n\nSources (the map's papers closest to the question):"
                                        f"\n\n{listed or '(none)'}\n\nThe reader's question: {query}\n\nWrite 2–3 "
                                        "paragraphs (about 300 words) answering it from these sources only: what "
                                        f"they show, and where they stop short of the question.{missing}\nCite each "
                                        "claim with its source number."}]


def abstracts_messages(query: str, papers: list[tuple[int, Paper, str]], uncovered: list[str] | None = None
                       ) -> list[dict]:
    listed = "\n\n".join(f"[{n}] {p.label()}\n{abstract}" for n, p, abstract in papers)
    missing = (f"\nParts of the topic none of these sources address: {'; '.join(uncovered)}. In Open questions, say "
               "plainly that the search found nothing on them; do not fill them in from general knowledge."
               if uncovered else "")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Topic: {query}\n\nSources (abstracts only, the most relevant first):\n\n"
                                        f"{listed}\n\nWrite a short literature review of the topic in Markdown with "
                                        "these sections, each a level-2 heading: ## Overview, ## Main themes, "
                                        "## Notable findings, ## Open questions. About 600 words. Write about the "
                                        "topic, not about each source in turn, and leave out what a source says about "
                                        "other subjects. Open questions are problems the sources state about this "
                                        "topic, not the limitations of a side method a source happens to use."
                                        f"{missing}\nCite each claim with its source number."}]


def thin_messages(query: str, papers: list[tuple[int, Paper, str]]) -> list[dict]:
    listed = "\n\n".join(f"[{n}] {p.label()}\n{abstract}" for n, p, abstract in papers)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Topic: {query}\n\nThe only sources a search found on this topic "
                                        f"(abstracts):\n\n{listed}\n\nIn one short paragraph per source (about 60 "
                                        "words each), say what it contributes to the topic. Do not write a general "
                                        "review: the sources are too few. Cite each claim with its source number."}]


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
    unsupported: int = 0


def finish(title: str, preface: str, sections: list[Section], registry: Registry) -> Result:
    """Renumber the citations, build the references and the whole Markdown."""
    texts, mapping = renumber([s.markdown for s in sections])
    for s, text in zip(sections, texts):
        s.markdown = text
    cited = sorted(mapping.items(), key=lambda kv: kv[1])
    sources = [{"n": new, "key": registry.papers[old].key, "title": registry.papers[old].title,
                "year": registry.papers[old].published_year or registry.papers[old].year,
                "authors": registry.papers[old].authors,
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


def _evidence(sections: list[Section]) -> dict[int, str]:
    """Each source's text across ``sections``: its abstract and the passages given for it."""
    out: dict[int, list[str]] = {}
    for s in sections:
        for n, label, text in s.evidence:
            if text and text not in out.setdefault(n, []):
                out[n].append(text)
    return {n: "\n…\n".join(texts) for n, texts in out.items()}


def _checked(text: str, evidence: dict[int, str], chat: Chat, counts: dict) -> str:
    from athena.evolution import verify
    text, found = verify.verify(text, evidence, chat)
    for key, value in found.items():
        counts[key] = counts.get(key, 0) + value
    return text


def _verified_note(counts: dict) -> str:
    if not counts.get("checked"):
        return ""
    removed = f"; {counts['no']} it did not support were removed" if counts.get("no") else ""
    return f" Each citation was checked against its source ({counts['checked']} checked{removed})."


def write_map_review(session, topic, chat: Chat, save: Callable[[dict], None], retrieve=None,
                     query: str | None = None, coverage=None) -> Result:
    """Outline, evidence, one call per section (the question's first when there is one), the overview, then
    citations checked against their sources and renumbered.

    ``coverage`` (``athena.evolution.coverage.Coverage``) says which parts of ``query`` the map covers.
    """
    from athena.evolution import ask
    registry = Registry()
    sections = outline(session, topic, registry)
    asked = query if query and query.strip().lower() not in {topic.name.lower(), topic.slug.replace("-", " ")} \
        else None
    uncovered = list(coverage.uncovered) if (asked and coverage is not None) else []
    if asked:
        sections.insert(1, Section("question", "Your question", task="question", question=asked))
    writable = [s for s in sections if s.by_model and s.key != "overview"]
    total = len(writable) + 3
    save({"progress": {"step": 1, "of": total, "label": "Reading the papers"}})
    passages = gather(session, topic, sections, registry, retrieve)
    if asked:
        try:
            hits = (retrieve or ask.retrieve)(session, topic, asked, None, chunk_limit=QUESTION_PASSAGES, per_paper=2,
                                              with_abstracts=True)
        except ask.AskUnavailable as exc:
            logger.warning(f"Review {topic.slug}: no passages for the question: {exc}")
            hits = []
        _add_hits(session, sections[1], hits, registry)
    logger.info(f"Review {topic.slug}: {passages} passages for {len(writable)} sections")
    removed, counts = 0, {}
    for i, section in enumerate(writable, start=2):
        save({"progress": {"step": i, "of": total, "label": f"Writing {section.title}"}})
        messages = question_messages(topic.name, asked, section, uncovered) if section.key == "question" \
            else section_messages(topic.name, section)
        text, *_ = chat(messages, QUESTION_TOKENS if section.key == "question" else SECTION_TOKENS)
        section.markdown, dropped = check_citations(_clean(text), {n for n, _, _ in section.evidence})
        removed += dropped
        section.markdown = _checked(section.markdown, _evidence([section]), chat, counts)
        save({"sections": _partial(sections)})
    save({"progress": {"step": total - 1, "of": total, "label": "Writing the overview"}})
    overview = sections[0]
    text, *_ = chat(overview_messages(topic.name, writable, asked), OVERVIEW_TOKENS)
    allowed = {n for s in writable for m in CITATION.finditer(s.markdown) for n in _numbers(m.group(1))}
    overview.markdown, dropped = check_citations(_clean(text), allowed)
    removed += dropped
    save({"progress": {"step": total, "of": total, "label": "Checking the citations"}})
    overview.markdown = _checked(overview.markdown, _evidence(writable), chat, counts)
    built = topic.built_at.date().isoformat() if topic.built_at else "an earlier build"
    scope = ""
    if asked and coverage is not None:
        scope = (f" The map covers {len(coverage.covered)} of the {len(coverage.parts)} parts of the question"
                 + (f"; it has nothing on: {'; '.join(uncovered)}." if uncovered else "."))
    preface = (f"Written by AI from the research map “{topic.name}” (built {built}): its milestones, open problems "
               f"and the papers' own text.{scope}{_verified_note(counts)} Check claims against the papers before "
               "relying on them.")
    title = short_title(asked) if asked else f"{topic.name}: a literature review"
    result = finish(title, preface, sections, registry)
    result.removed, result.unsupported = removed, counts.get("no", 0)
    if removed:
        logger.info(f"Review {topic.slug}: removed {removed} citations to sources a section was not given")
    return result


def _add_hits(session, section: Section, hits, registry: Registry) -> None:
    from athena.core.models import EvoPaper
    from athena.evolution import ask
    for hit in hits:
        paper = session.get(EvoPaper, UUID(hit.paper_id))
        if paper is None:
            continue
        n = registry.number(_evo_paper(paper, hit.named_method))
        where = "Abstract" if getattr(hit, "abstract_only", False) else \
            f"{ask.SECTION_LABELS.get(hit.section_type, 'Body')}: {hit.heading}"
        section.evidence.append((n, f"{_evo_paper(paper, hit.named_method).label()}, {where}",
                                 hit.text[:PASSAGE_CHARS]))


def _search_paper(p: dict) -> Paper:
    return Paper(key=f"search:{p.get('id') or p['title']}", title=p["title"], year=p.get("year"),
                 authors=list(p.get("authors") or []), venue=p.get("venue"), doi=p.get("doi"),
                 arxiv_id=p.get("arxiv_id"), url=p.get("url"))


def write_abstracts_review(query: str, papers: list[dict], chat: Chat, save: Callable[[dict], None],
                           found=None, note: str = "") -> Result:
    """A review from the relevant papers' abstracts, checked and referenced like a map review.

    ``papers`` are the sources, most relevant first; ``found`` (``review_search.Found``) says how they were found
    and which parts of the question none of them covers. With fewer than MIN_ABSTRACT_PAPERS the review says so
    and only describes what it found.
    """
    registry = Registry()
    numbered = []
    for p in papers[:ABSTRACT_PAPERS]:
        if not p.get("abstract"):
            continue
        paper = _search_paper(p)
        numbered.append((registry.number(paper), paper, p["abstract"][:ABSTRACT_CHARS]))
    searched = found.searched if found is not None else len(papers)
    uncovered = found.uncovered if found is not None else []
    if not searched:
        raise ValueError("The search found no papers with abstracts (Semantic Scholar may be rate-limiting). Try "
                         "again in a few minutes, or build a map of the topic.")
    how = (f"{searched} papers found by searching Semantic Scholar, arXiv and Athena's library ({len(found.queries)} "
           "searches, then the references and citers of the best papers)" if found is not None
           else f"{searched} search results")
    map_hint = ("No research map covers this question. Building one (Maps → New map, or build_map for agents) gives "
                "a review grounded in the papers' full text and citation history.")
    missing = f" Nothing found on: {'; '.join(uncovered)}." if uncovered else ""
    counts: dict = {}
    if len(numbered) < MIN_ABSTRACT_PAPERS:
        save({"progress": {"step": 1, "of": 2, "label": "Describing the few relevant papers"}})
        sections = [Section("found", "What the search found", level=2)]
        if numbered:
            text, *_ = chat(thin_messages(query, numbered), THIN_TOKENS)
            body, removed = check_citations(_clean(text), {n for n, _, _ in numbered})
            save({"progress": {"step": 2, "of": 2, "label": "Checking the citations"}})
            sections[0].markdown = _checked(body, {n: a for n, _, a in numbered}, chat, counts)
        else:
            body, removed = "", 0
            sections[0].markdown = "No paper the search found is about this topic."
        if uncovered:
            sections.append(Section("missing", "Not covered", level=2,
                                    markdown="\n".join(f"- {c}" for c in uncovered)))
        sections.append(Section("next", "Next step", level=2, markdown=(
            "Too few relevant papers for a review: the core literature is probably missing from this search, not "
            "absent from the field. Build a research map of the topic (it collects papers by citation, not by "
            "keyword), or try the field's own names for it.")))
        preface = (f"{note}Of {how}, only {len(numbered)} are about this topic: too few to write a review from."
                   f"{missing} {map_hint}")
        result = finish(short_title(query), preface, sections, registry)
        result.removed, result.unsupported = removed, counts.get("no", 0)
        return result

    save({"progress": {"step": 1, "of": 2, "label": "Writing from the abstracts"}})
    text, *_ = chat(abstracts_messages(query, numbered, uncovered), ABSTRACTS_TOKENS)
    body, removed = check_citations(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip(),
                                    {n for n, _, _ in numbered})
    save({"progress": {"step": 2, "of": 2, "label": "Checking the citations"}})
    body = _checked(body, {n: a for n, _, a in numbered}, chat, counts)
    section = Section("review", "Review", level=2, markdown=re.sub(r"^#{1,2} ", "### ", body, flags=re.M))
    preface = (f"{note}Written by AI from the abstracts of the {len(numbered)} most relevant of {how}. It does not "
               f"read the papers' full text or trace their history.{missing}{_verified_note(counts)} {map_hint} "
               "Check claims against the papers.")
    result = finish(short_title(query), preface, [section], registry)
    result.removed, result.unsupported = removed, counts.get("no", 0)
    return result


def _partial(sections: list[Section]) -> list[dict]:
    return [{"key": s.key, "title": s.title, "level": s.level, "markdown": s.markdown} for s in sections]


# ── running a saved review ───────────────────────────────────────────


def model_chat(user_id, model_used: dict) -> Chat:
    """A chat call through athena.core.llm that records its usage against the user."""
    from athena.core import llm, usage
    from athena.model_server import activity
    model = llm.chat_model("lit_review")
    model_used["model"] = model

    def chat(messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
        with activity.track("lit_review", model, user_id=user_id) as call:
            resp = llm.chat_client(model=model).chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.2, extra_body=llm.chat_extra())
            tokens_in, tokens_out = usage.tokens_of(resp.usage)
            call.tokens(tokens_in, tokens_out)
        usage.add("lit_review", model, tokens_in, tokens_out, user_id=user_id)
        model_used["in"] = model_used.get("in", 0) + tokens_in
        model_used["out"] = model_used.get("out", 0) + tokens_out
        return resp.choices[0].message.content or "", tokens_in, tokens_out

    return chat


def find_sources(query: str, chat: Chat, user_id=None, save: Callable[[dict], None] | None = None, embed=None,
                 plan=None):
    """The abstracts review's papers (``athena.evolution.review_search``), with its progress shown."""
    from athena.evolution import review_search

    def progress(label: str) -> None:
        if save is not None:
            save({"progress": {"step": 0, "of": 2, "label": label}})
    return review_search.find_sources(query, chat, embed or review_search.model_embed(user_id),
                                      limit=ABSTRACT_PAPERS, progress=progress, plan=plan)


def map_covers(session, topic, query: str, chat: Chat, save: Callable[[dict], None]):
    """The review's plan, whether ``query`` is about the map's field (False when its subject does not name the map
    or the model says it is about another subject; None when the model could not say), and which of its parts the
    map's papers cover."""
    from athena.evolution import coverage, review_search
    save({"progress": {"step": 0, "of": 2, "label": f"Checking what the map “{topic.name}” covers"}})
    plan = review_search.make_plan(query, chat)
    named = coverage.names_map(plan.subject, topic)
    field = coverage.about_field(topic, query, chat) if named else False
    logger.info(f"Review: subject {plan.subject!r} names {topic.slug}: {named}; about its field: {field}")
    return plan, field, coverage.check(session, topic, query, chat, plan.concepts)


def run(review_id, chat: Chat | None = None, retrieve=None, papers=None, embed=None, coverage=None) -> dict:
    """Write a saved review, recording progress as it goes. Returns its status.

    Tests pass ``papers`` (an abstracts review's sources, skipping the search), ``retrieve`` and ``coverage`` (a map
    review's passages and how much of the question the map covers) and ``embed``.
    """
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
            plan, note, field = None, "", None
            if review.mode == "map":
                from athena.evolution.coverage import MIN_SHARE
                topic = session.get(EvoTopic, review.topic_id) if review.topic_id else None
                if topic is None or topic.built_at is None:
                    raise ValueError("The map is gone or not built")
                if review.query and coverage is None:
                    try:
                        plan, field, coverage = map_covers(session, topic, review.query, chat, save)
                    except Exception as exc:  # the review is still written, without the note on what it covers
                        logger.warning(f"Review {review_id}: map coverage not checked: {exc}")
                if coverage is not None:
                    logger.info(f"Review {review_id}: {topic.slug}: about its field {field}; covers "
                                f"{coverage.share:.0%} of the question ({coverage.method}): {coverage.parts}")
                # The model's answer decides; without one, the share of the parts the map covers.
                elsewhere = field is False or (field is None and coverage is not None and coverage.share < MIN_SHARE)
                if review.query and elsewhere:
                    # The query only named the map: write from search results, and say why.
                    why = ("the question is about another subject that only mentions its field (“"
                           f"{plan.subject if plan else review.query}”)" if field is False
                           else f"its papers cover only {len(coverage.covered)} of the question's "
                                f"{len(coverage.parts)} parts")
                    note = (f"The research map “{topic.name}” matched the question, but {why}, so this review is "
                            "written from a literature search instead. ")
                    save({"mode": "abstracts", "topic_id": None})
                else:
                    result = write_map_review(session, topic, chat, save, retrieve, query=review.query,
                                              coverage=coverage)
                    review.built_at = topic.built_at
            if review.mode == "abstracts" and papers is not None:
                result = write_abstracts_review(review.query or "", papers, chat, save, note=note)
            elif review.mode == "abstracts":
                found = find_sources(review.query or "", chat, review.user_id, save, embed, plan)
                result = write_abstracts_review(review.query or "", found.sources, chat, save, found, note=note)
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
        return {"status": "done", "citations_removed": result.removed, "citations_unsupported": result.unsupported}


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
