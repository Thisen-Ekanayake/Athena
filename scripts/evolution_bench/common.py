"""
Shared helpers for the Phase 0 research-evolution benchmark.

Holds the test-paper registry, the known citing → cited pairs, GROBID TEI
parsing (including fallbacks for citations GROBID fails to link), and the
rule-based heading → section-type mapping.
"""
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from lxml import etree
from loguru import logger

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
OUT_DIR = BENCH_DIR / "out"
TEI_DIR = OUT_DIR / "tei"
PDF_DIR = OUT_DIR / "pdfs"
LABELS_PATH = BENCH_DIR / "labels.csv"
RESULTS_PATH = OUT_DIR / "results.csv"
MODELS_DIR = REPO_ROOT / "models"
LOCAL_PAPERS_DIR = Path("/ml/Research Papers")
GROBID_URL = "http://localhost:8070"

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@dataclass(frozen=True)
class Paper:
    key: str
    title: str
    year: int
    arxiv_id: str
    local_glob: str | None = None  # file in /ml/Research Papers; otherwise downloaded from arXiv


PAPERS = [
    Paper("transformer", "Attention Is All You Need", 2017, "1706.03762",
          local_glob="Attention Is All You Need.pdf"),
    Paper("bert", "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding", 2018,
          "1810.04805", local_glob="BERT: Pre-training*"),
    Paper("lora", "LoRA: Low-Rank Adaptation of Large Language Models", 2021, "2106.09685",
          local_glob="LoRA Finetune.pdf"),
    Paper("pissa", "PiSSA: Principal Singular Values and Singular Vectors Adaptation of Large Language Models", 2024,
          "2404.02948", local_glob="NeurIPS-2024-pissa*"),
    Paper("yolo", "You Only Look Once: Unified, Real-Time Object Detection", 2016, "1506.02640",
          local_glob="yolo.pdf"),
    Paper("cot", "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models", 2022, "2201.11903",
          local_glob="Chain-of-Thought*"),
    Paper("clip", "Learning Transferable Visual Models From Natural Language Supervision", 2021, "2103.00020",
          local_glob="CLIP.pdf"),
    # Cited papers fetched from arXiv so that the known pairs below have both sides.
    Paper("seq2seq", "Sequence to Sequence Learning with Neural Networks", 2014, "1409.3215"),
    Paper("bahdanau", "Neural Machine Translation by Jointly Learning to Align and Translate", 2014, "1409.0473"),
    Paper("elmo", "Deep contextualized word representations", 2018, "1802.05365"),
    Paper("adapters", "Parameter-Efficient Transfer Learning for NLP", 2019, "1902.00751"),
    Paper("qlora", "QLoRA: Efficient Finetuning of Quantized LLMs", 2023, "2305.14314"),
    Paper("dora", "DoRA: Weight-Decomposed Low-Rank Adaptation", 2024, "2402.09353"),
    Paper("rcnn", "Rich feature hierarchies for accurate object detection and semantic segmentation", 2014,
          "1311.2524"),
    Paper("fast_rcnn", "Fast R-CNN", 2015, "1504.08083"),
    Paper("faster_rcnn", "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks", 2015,
          "1506.01497"),
]
PAPERS_BY_KEY = {p.key: p for p in PAPERS}

# Cited works we only need to recognise in bibliographies (no PDF needed).
REFERENCE_ONLY_TITLES = {
    "gpt": "Improving Language Understanding by Generative Pre-Training",
    "dpm": "Object Detection with Discriminatively Trained Part Based Models",
    "convs2s": "Convolutional Sequence to Sequence Learning",
}
KNOWN_TITLES = {p.key: p.title for p in PAPERS} | REFERENCE_ONLY_TITLES
# Other titles the same work is cited under (BERT cites GPT by its blog-post title).
TITLE_ALIASES = {
    "gpt": ["Improving language understanding with unsupervised learning"],
}
ARXIV_TO_KEY = {p.arxiv_id: p.key for p in PAPERS}

# (citing, cited) pairs where the citing paper is known to improve on the cited one.
KNOWN_PAIRS = [
    ("pissa", "lora"), ("qlora", "lora"), ("dora", "lora"), ("lora", "adapters"),
    ("bert", "elmo"), ("bert", "gpt"),
    ("transformer", "seq2seq"), ("transformer", "bahdanau"), ("transformer", "convs2s"),
    ("fast_rcnn", "rcnn"), ("faster_rcnn", "fast_rcnn"), ("faster_rcnn", "rcnn"),
    ("yolo", "rcnn"), ("yolo", "dpm"), ("yolo", "fast_rcnn"), ("yolo", "faster_rcnn"),
]

SECTION_TYPES = [
    "intro", "related_work", "method", "results", "discussion",
    "limitations", "conclusion", "future_work", "other",
]
TASK_LABELS = {
    "A": ["gap", "not_gap"],
    "B": ["addresses_limitation", "criticises", "extends_or_uses", "compares", "background"],
    "C": SECTION_TYPES,
}
# Task B labels that say the citing paper states a limitation of the cited one: the evidence strict links need.
LIMITATION_LABELS = {"addresses_limitation", "criticises"}

# Order matters: the first matching rule wins ("Conclusion and future work" -> conclusion).
_SECTION_RULES = [
    ("limitations", r"limitation"),
    ("conclusion", r"conclu|summary|closing remark"),
    ("future_work", r"future (work|direction|research)"),
    ("discussion", r"discussion"),
    ("related_work", r"related work|prior work|previous work|background|preliminar|literature"),
    ("intro", r"introduction|motivation"),
    ("other", r"acknowledg|appendix|broader impact|ethic|reproducib|author contribution"),
    ("results", r"experiment|result|evaluation|benchmark|ablation|empirical|comparison|analys"),
    ("method", r"method|approach|model|architecture|framework|algorithm|proposed|formulation|training|\bour\b"),
]


def classify_heading(heading: str) -> str | None:
    """Map a section heading to a standard section type, or None when no rule matches."""
    text = heading.strip().lower()
    for section_type, pattern in _SECTION_RULES:
        if re.search(pattern, text):
            return section_type
    return None


# ── TEI parsing ────────────────────────────────────────────────────────


@dataclass
class BibEntry:
    title: str
    surname: str      # first author's surname, lower-cased
    year: str
    suffix: str       # "a" in "2018a", when GROBID kept it
    arxiv_id: str


@dataclass
class Sentence:
    text: str
    refs: list[str] = field(default_factory=list)  # bibliography xml:ids cited in this sentence


@dataclass
class Section:
    heading: str
    number: str | None
    section_type: str
    rule_type: str | None  # what the heading rules said before inheriting from the parent section
    sentences: list[Sentence]


@dataclass
class ParsedPaper:
    key: str
    tei_title: str
    abstract: list[Sentence]
    sections: list[Section]
    bib: dict[str, BibEntry]  # xml:id -> entry
    fallback_links: int = 0   # in-text citations GROBID left unlinked that we resolved ourselves


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
        raw = " ".join(bibl.itertext())
        arxiv = re.search(r"(\d{4}\.\d{4,5})", raw)
        bib[xml_id] = BibEntry(
            title=title,
            surname=_text(surname_el).lower(),
            year=year,
            suffix=suffix,
            arxiv_id=arxiv.group(1) if arxiv else "",
        )
    return bib


_AUTHOR_YEAR = re.compile(
    r"([A-Z][\w'\-]+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][\w'\-]+)?,?\s*\(?((?:19|20)\d{2})([a-z]?)"
)


def _link_author_year(text: str, bib: dict[str, BibEntry]) -> list[str]:
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

    def read(self, container) -> list[Sentence]:
        out: list[Sentence] = []
        for p in container.iter(f"{TEI}p"):
            units = p.findall(f"{TEI}s") or [p]
            for unit in units:
                text = _text(unit)
                if not text:
                    continue
                refs = []
                for ref in unit.iter(f"{TEI}ref"):
                    if ref.get("type") != "bibr":
                        continue
                    if ref.get("target"):
                        refs += [t.lstrip("#") for t in ref.get("target").split()]
                    else:
                        linked = _link_author_year(_text(ref), self.bib)
                        self.fallback_links += len(linked)
                        refs += linked
                out.append(Sentence(text=text, refs=refs))
        return out


def parse_tei(key: str, path: Path) -> ParsedPaper:
    root = etree.parse(str(path)).getroot()
    bib = _parse_bib(root)
    reader = _SentenceReader(bib)

    tei_title = _text(root.find(f".//{TEI}teiHeader//{TEI}titleStmt/{TEI}title"))
    abstract_el = root.find(f".//{TEI}profileDesc/{TEI}abstract")
    abstract = reader.read(abstract_el) if abstract_el is not None else []

    sections: list[Section] = []
    top_level_types: dict[str, str] = {}
    body = root.find(f".//{TEI}text/{TEI}body")
    for div in (body.findall(f"{TEI}div") if body is not None else []):
        head = div.find(f"{TEI}head")
        heading = _text(head)
        number = head.get("n") if head is not None else None
        rule_type = classify_heading(heading) if heading else None
        section_type = rule_type
        if section_type is None and number:
            # Subsection like "3.2": inherit the type of section "3".
            section_type = top_level_types.get(number.split(".")[0])
        if section_type is None and not heading and sections:
            # Untitled continuation block: same type as the section before it.
            section_type = sections[-1].section_type
        section_type = section_type or "other"
        if number and "." not in number.strip("."):
            top_level_types[number.strip(".")] = section_type
        sentences = reader.read(div)
        if sentences:
            sections.append(Section(heading or "(untitled)", number, section_type, rule_type, sentences))

    return ParsedPaper(key=key, tei_title=tei_title, abstract=abstract, sections=sections, bib=bib,
                       fallback_links=reader.fallback_links)


def load_parsed(keys: list[str] | None = None) -> dict[str, ParsedPaper]:
    """Parse every saved TEI file (or just ``keys``)."""
    parsed = {}
    for paper in PAPERS:
        if keys and paper.key not in keys:
            continue
        path = TEI_DIR / f"{paper.key}.tei.xml"
        if path.exists():
            parsed[paper.key] = parse_tei(paper.key, path)
    return parsed


# ── Reference matching ─────────────────────────────────────────────────


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def match_known_title(title: str, threshold: float = 0.8) -> str | None:
    """Return the KNOWN_TITLES key whose title (or alias) best matches ``title`` (Jaccard on tokens).

    0.6 was too loose: "QA-LoRA: Quantization-aware low-rank adaptation of large language models" matched LoRA.
    """
    tokens = _tokens(title)
    if not tokens:
        return None
    best_key, best_score = None, 0.0
    for key, known in KNOWN_TITLES.items():
        for candidate in [known, *TITLE_ALIASES.get(key, [])]:
            known_tokens = _tokens(candidate)
            score = len(tokens & known_tokens) / len(tokens | known_tokens)
            if score > best_score:
                best_key, best_score = key, score
    return best_key if best_score >= threshold else None


def match_known(entry: BibEntry) -> str | None:
    """Identify a bibliography entry: arXiv ID first, then title."""
    if entry.arxiv_id in ARXIV_TO_KEY:
        return ARXIV_TO_KEY[entry.arxiv_id]
    return match_known_title(entry.title)


def resolve_refs(paper: ParsedPaper) -> dict[str, str]:
    """Map bibliography xml:ids in ``paper`` to KNOWN_TITLES keys where they match."""
    resolved = {}
    for xml_id, entry in paper.bib.items():
        key = match_known(entry)
        if key and key != paper.key:
            resolved[xml_id] = key
    return resolved


# ── PDFs ───────────────────────────────────────────────────────────────


def pdf_path(paper: Paper) -> Path:
    """Return a local PDF for ``paper``, downloading it from arXiv when there is no local copy."""
    if paper.local_glob:
        matches = sorted(LOCAL_PAPERS_DIR.glob(paper.local_glob))
        if not matches:
            raise FileNotFoundError(f"No file matching {paper.local_glob!r} in {LOCAL_PAPERS_DIR}")
        return matches[0]

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / f"{paper.key}.pdf"
    if target.exists() and target.stat().st_size > 10_000:
        return target
    url = f"https://arxiv.org/pdf/{paper.arxiv_id}"
    logger.info(f"Downloading {paper.key} from {url}")
    headers = {"User-Agent": "athena-evolution-bench/0.1 (research prototype)"}
    with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
    target.write_bytes(resp.content)
    time.sleep(3)  # arXiv asks for at most one request every 3 seconds
    return target


# ── Labels ─────────────────────────────────────────────────────────────

LABEL_COLUMNS = ["id", "task", "paper", "cited", "section", "sentence", "suggested", "label", "notes", "labeller"]


def read_labels(path: Path = LABELS_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def labelled_rows(task: str) -> list[dict]:
    """Rows of one task whose label is filled in with an allowed value."""
    allowed = set(TASK_LABELS[task])
    rows = [r for r in read_labels() if r["task"] == task]
    bad = [r["id"] for r in rows if r["label"].strip() and r["label"].strip() not in allowed]
    if bad:
        raise ValueError(f"Task {task}: rows {bad} have labels outside {sorted(allowed)}")
    return [r for r in rows if r["label"].strip()]
