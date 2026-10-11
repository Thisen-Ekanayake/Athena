"""
Parse GROBID TEI XML into sections, sentences and resolved citations.

Moved from the Phase 0 benchmark (scripts/evolution_bench/common.py), with
the fixes Phase 0 called for:

- In-text citations GROBID leaves unlinked ("Peters et al., 2018a") are
  resolved by first-author surname and year.
- Section types come from heading rules, then three deterministic additions:
  a heading naming the paper's own method is ``method``; untyped sections
  between the introduction and the experiments are ``method``; analysis and
  error-study headings are ``results`` (in the rules).
- Figure text, table cells and NeurIPS checklist lines are dropped, and so is
  everything from a checklist heading on. Junk headings GROBID makes from
  figure labels or example dialogue ("27.41", "Guanaco:") are folded into
  the section before them.
- Each citation records the words just before its marker, so "LoRA [28]"
  yields "LoRA" for named-method detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

SECTION_TYPES = [
    "abstract", "intro", "related_work", "method", "results", "discussion",
    "limitations", "conclusion", "future_work", "other",
]

# Order matters: the first matching rule wins ("Conclusion and future work" -> conclusion).
_SECTION_RULES = [
    ("limitations", r"limitation"),
    ("conclusion", r"conclu|summary|closing remark"),
    ("future_work", r"future (work|direction|research)"),
    ("discussion", r"discussion"),
    ("related_work", r"related work|prior work|previous work|background|preliminar|literature"),
    ("intro", r"introduction|motivation"),
    ("other", r"acknowledg|appendix|broader impact|ethic|reproducib|author contribution"),
    ("results", r"experiment|result|evaluation|benchmark|ablation|empirical|comparison|analys|error"),
    ("method", r"method|approach|model|architecture|framework|algorithm|proposed|formulation|training|\bour\b"),
]
_CHECKLIST_HEADING = re.compile(r"checklist", re.IGNORECASE)
_CHECKLIST_LINE = re.compile(r"^\s*(answer|justification|guidelines)\s*:|\[(yes|no|n/?a)\]", re.IGNORECASE)
_CAPTION = re.compile(r"^\s*(fig(ure)?\.?|table|tab\.)\s*\d+\s*[:.|]", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*[.,;:)?!]?")
# Up to three words right before a citation marker ("Faster R-CNN", "Swin Transformer", "LoRA+").
_WORD_RE = r"[A-Za-z][\w\-.+]*[\w+]"
_LAST_WORDS = re.compile(rf"((?:{_WORD_RE}\s+){{0,2}}{_WORD_RE})\W*$")
_OPEN_GROUP = re.compile(r"[\[(][^\[\]()A-Za-z]*$")


def classify_heading(heading: str) -> str | None:
    """Map a section heading to a standard section type, or None when no rule matches."""
    text = heading.strip().lower()
    for section_type, pattern in _SECTION_RULES:
        if re.search(pattern, text):
            return section_type
    return None


def is_junk_sentence(text: str) -> bool:
    """Figure text, table cells, formulas and checklist lines rather than prose."""
    words = text.split()
    if len(words) < 5 or _CAPTION.match(text) or _CHECKLIST_LINE.search(text):
        return True
    prose = sum(1 for w in words if len(w) > 1 and _WORD.fullmatch(w))
    return prose / len(words) < 0.5


def is_junk_heading(heading: str) -> bool:
    """Headings GROBID makes from figure labels, numbers or example dialogue."""
    words = heading.split()
    if not any(len(w) >= 3 and w[0].isalpha() for w in words):
        return True                          # "27.41", "Q L o R A -A ll"
    if sum(len(w) == 1 for w in words) > len(words) / 2:
        return True
    if heading.rstrip().endswith(":") and len(words) <= 2:
        return True                          # "Guanaco:"
    return heading.rstrip().endswith((".", "?")) and len(words) > 6  # a sentence, not a heading


def mention_before(prefix: str) -> str | None:
    """Up to three words right before a citation marker: '...adapters like Faster R-CNN [' -> 'like Faster R-CNN'.

    ``athena.evolution.names`` picks the name out of these. Only the first reference of a marker group
    gets words: in "R-CNN [12, 34]" they name reference 12, not 34. Names ending in digits survive:
    "GPT-3 [5]", "YOLOv3 [12]".
    """
    tail = prefix[-80:].rstrip()
    group = _OPEN_GROUP.search(tail)
    if group:
        if re.search(r"\d", group.group(0)):
            return None  # a later reference in a group like "[12, 34]"
        tail = tail[:group.start()]
    match = _LAST_WORDS.search(tail.rstrip(" ,;"))
    return match.group(1) if match else None


@dataclass
class BibEntry:
    title: str
    surname: str      # first author's surname, lower-cased
    year: str
    suffix: str       # "a" in "2018a", when GROBID kept it
    arxiv_id: str
    doi: str = ""


@dataclass
class Sentence:
    text: str
    refs: list[str] = field(default_factory=list)          # bibliography xml:ids cited in this sentence
    mentions: dict[str, str] = field(default_factory=dict)  # xml:id -> word right before its marker
    # xml:id -> the sentence with that reference's markers wrapped in [[ ]], so a classifier can tell which
    # citation is the cited paper ("... very slow, taking 40 s per image [[[14]]]").
    marked: dict[str, str] = field(default_factory=dict)


@dataclass
class Section:
    heading: str
    number: str | None
    section_type: str
    rule_type: str | None  # what the heading rules said before inheritance and the Phase 0 additions
    sentences: list[Sentence]


@dataclass
class ParsedPaper:
    title: str
    sections: list[Section]  # the abstract first, as section type "abstract"
    bib: dict[str, BibEntry]  # xml:id -> entry
    fallback_links: int = 0   # in-text citations GROBID left unlinked that were resolved here
    dropped_sentences: int = 0


def _clean(text: str) -> str:
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _text(el) -> str:
    return _clean("".join(el.itertext())) if el is not None else ""


def _parse_bib(root) -> dict[str, BibEntry]:
    bib: dict[str, BibEntry] = {}
    for bibl in root.iter(f"{TEI}biblStruct"):
        xml_id = bibl.get(XML_ID)
        if not xml_id:
            continue
        title = ""
        for path in (f"{TEI}analytic/{TEI}title", f"{TEI}monogr/{TEI}title"):
            title = _text(bibl.find(path))
            if title:
                break
        # GROBID sometimes folds "2018a." into the title of author-year references.
        suffix, year = "", ""
        m = re.match(r"((?:19|20)\d{2})([a-z])?\.\s*(.*)", title)
        if m:
            year, suffix, title = m.group(1), m.group(2) or "", m.group(3)
        surname_el = bibl.find(f".//{TEI}author/{TEI}persName/{TEI}surname")
        date_el = bibl.find(f".//{TEI}date")
        if not year and date_el is not None:
            year = (date_el.get("when") or "")[:4]
        doi_el = bibl.find(f".//{TEI}idno[@type='DOI']")
        raw = " ".join(bibl.itertext())
        arxiv = re.search(r"(\d{4}\.\d{4,5})", raw)
        bib[xml_id] = BibEntry(
            title=title,
            surname=_text(surname_el).lower(),
            year=year,
            suffix=suffix,
            arxiv_id=arxiv.group(1) if arxiv else "",
            doi=_text(doi_el).lower(),
        )
    return bib


_AUTHOR_YEAR = re.compile(
    r"([A-Z][\w'\-]+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][\w'\-]+)?,?\s*\(?((?:19|20)\d{2})([a-z]?)"
)


def link_author_year(text: str, bib: dict[str, BibEntry]) -> list[str]:
    """Resolve 'Peters et al., 2018a'-style citations that GROBID did not link."""
    ids = []
    for surname, year, suffix in _AUTHOR_YEAR.findall(text):
        candidates = [k for k, e in bib.items() if e.surname == surname.lower() and e.year == year]
        if len(candidates) > 1 and suffix:
            exact = [k for k in candidates if bib[k].suffix == suffix]
            position = ord(suffix) - ord("a")
            if exact:
                candidates = exact
            elif position < len(candidates):
                # Bibliographies list 2018a before 2018b.
                candidates = [candidates[position]]
        if len(candidates) == 1:
            ids.append(candidates[0])
    return ids


class _SentenceReader:
    def __init__(self, bib: dict[str, BibEntry]):
        self.bib = bib
        self.fallback_links = 0
        self.dropped = 0

    def read(self, container) -> list[Sentence]:
        out: list[Sentence] = []
        for p in container.iter(f"{TEI}p"):
            for unit in p.findall(f"{TEI}s") or [p]:
                sentence = self._sentence(unit)
                if sentence is None:
                    continue
                if is_junk_sentence(sentence.text):
                    self.dropped += 1
                    continue
                out.append(sentence)
        return out

    def _sentence(self, unit) -> Sentence | None:
        parts: list[str] = []
        marks: list[tuple[etree._Element, int, int]] = []  # (ref, start, end) in the raw text

        def walk(el):
            if el.text:
                parts.append(el.text)
            for child in el:
                is_ref = child.tag == f"{TEI}ref" and child.get("type") == "bibr"
                start = len("".join(parts))
                walk(child)
                if is_ref:
                    marks.append((child, start, len("".join(parts))))
                if child.tail:
                    parts.append(child.tail)

        walk(unit)
        raw = "".join(parts)
        text = _clean(raw)
        if not text:
            return None
        sentence = Sentence(text=text)
        spans: dict[str, list[tuple[int, int]]] = {}
        for ref, start, end in marks:
            if ref.get("target"):
                ids = [t.lstrip("#") for t in ref.get("target").split()]
            else:
                ids = link_author_year(_text(ref), self.bib)
                self.fallback_links += len(ids)
            mention = mention_before(_clean(raw[:start]))
            for xml_id in ids:
                if xml_id not in sentence.refs:
                    sentence.refs.append(xml_id)
                if mention:
                    sentence.mentions.setdefault(xml_id, mention)
                spans.setdefault(xml_id, []).append((start, end))
        for xml_id, ranges in spans.items():
            marked, last = [], 0
            for start, end in ranges:
                marked += [raw[last:start], "[[", raw[start:end], "]]"]
                last = end
            sentence.marked[xml_id] = _clean("".join(marked) + raw[last:])
        return sentence


def _assign_types(raw: list[dict], method_name: str | None) -> list[Section]:
    sections: list[Section] = []
    top_level: dict[str, str] = {}
    seen_intro = seen_results = False
    for sec in raw:
        heading, number = sec["heading"], sec["number"]
        rule_type = classify_heading(heading) if heading else None
        section_type = rule_type
        top = number.strip(".").split(".")[0] if number else None
        if section_type is None and number and "." in number.strip("."):
            section_type = top_level.get(top)  # subsection "3.2" inherits from section "3"
        if section_type is None and method_name and heading and method_name.lower() in heading.lower():
            section_type = "method"
        if section_type is None and seen_intro and not seen_results:
            section_type = "method"
        if section_type is None and not number and sections:
            section_type = sections[-1].section_type  # unnumbered continuation of the section before
        section_type = section_type or "other"
        if number and "." not in number.strip("."):
            top_level[top] = section_type
        seen_intro = seen_intro or section_type in ("intro", "related_work")
        seen_results = seen_results or section_type == "results"
        sections.append(Section(heading or "(untitled)", number, section_type, rule_type, sec["sentences"]))
    return sections


def parse_tei(source: str | bytes | Path, method_name: str | None = None) -> ParsedPaper:
    """Parse a GROBID TEI document. ``method_name`` is the paper's own method ("QLoRA"), if known."""
    if isinstance(source, Path):
        root = etree.parse(str(source)).getroot()
    else:
        root = etree.fromstring(source.encode() if isinstance(source, str) else source)
    bib = _parse_bib(root)
    reader = _SentenceReader(bib)

    title = _text(root.find(f".//{TEI}teiHeader//{TEI}titleStmt/{TEI}title"))
    raw: list[dict] = []
    abstract_el = root.find(f".//{TEI}profileDesc/{TEI}abstract")
    abstract = reader.read(abstract_el) if abstract_el is not None else []

    body = root.find(f".//{TEI}text/{TEI}body")
    for div in (body.findall(f"{TEI}div") if body is not None else []):
        head = div.find(f"{TEI}head")
        heading = _text(head)
        if heading and _CHECKLIST_HEADING.search(heading):
            break  # the checklist runs to the end of the paper
        sentences = reader.read(div)
        if heading and is_junk_heading(heading):
            if raw:
                raw[-1]["sentences"] += sentences
            continue
        if sentences or heading:
            # Empty headed divs stay for typing: "3. Experiments" often has no text of its own, but
            # its subsections inherit its type.
            raw.append({"heading": heading, "number": head.get("n") if head is not None else None,
                        "sentences": sentences})

    sections = [s for s in _assign_types(raw, method_name) if s.sentences]
    if abstract:
        sections.insert(0, Section("Abstract", None, "abstract", "abstract", abstract))
    return ParsedPaper(title=title, sections=sections, bib=bib, fallback_links=reader.fallback_links,
                       dropped_sentences=reader.dropped)
