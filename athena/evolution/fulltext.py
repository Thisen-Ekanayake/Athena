"""
Tier 2 full text: PDFs -> GROBID -> sections, chunks and citing sentences.

Tier 2 is a topic's milestones, its main path and each milestone's strongest
successors (``athena.database.evolution.tier2_papers``). For each of them:

1. Download the PDF, from arXiv when the paper has an arXiv ID (at most one
   request every three seconds, as arXiv asks), else from the open-access URL
   OpenAlex lists. PDFs and TEI files are kept on disk, so re-parsing with
   better rules does not need the network or GROBID again.
2. Parse it with GROBID and ``athena.evolution.tei``.
3. Resolve its bibliography to papers Athena knows: arXiv ID, DOI, exact
   title, then a fuzzy title match against the papers OpenAlex or Semantic
   Scholar already say it cites.
4. Store sections, ~300-word chunks that never cross a section, and every
   sentence citing a known paper. Citations GROBID finds that neither source
   had become ``evo_citations`` rows with source "grobid".

Papers without an open PDF get their citing sentences from Semantic
Scholar's contexts instead (no sections, so no chunks).

No GPU work happens here: chunks wait for the embedder and citing sentences
for the classifier (``athena.evolution.gpu``).
"""
from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

import httpx
from loguru import logger

from athena.core.config_store import get_setting
from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.evolution.corpus import same_title, title_key
from athena.evolution.milestones import named_method
from athena.evolution.semantic_scholar import S2Ref, SemanticScholarAuthError, SemanticScholarClient
from athena.evolution.tei import BibEntry, ParsedPaper, mention_before, parse_tei

CHUNK_WORDS = 300
ARXIV_INTERVAL = 3.0
GROBID_WORKERS = 3
BATCH = 24  # papers fetched, parsed and saved together, so an interrupted run keeps its progress
USER_AGENT = "athena-research-evolution/0.2 (research prototype)"
# Contrast and criticism cues. Random citing sentences state a limitation of the cited paper only
# 3 times in 40 (Phase 0), so only sentences with a cue go to the classifier.
CONTRAST_CUES = re.compile(
    r"\b(however|unlike|in contrast|contrary|whereas|but|although|suffer|slow|expensive|costly|inefficien|limit"
    r"|fail|cannot|unable|drawback|shallow|bottleneck|complex|inelegant|only|lack|difficult|problem|issue"
    r"|prohibitive|sub-?optimal|degrad|gap|overhead|instabil|unstable|sensitiv|restrict|requir|memory|latency)",
    re.IGNORECASE,
)
_CHUNK_NAMESPACE = UUID("5b0f6e2a-9d43-4c1e-a7b5-3f1f0a9b2c6d")
_VERSION = re.compile(r"v\d+$")
_MARKER = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]|\((?:[A-Z][^()]{0,60}?(?:19|20)\d{2}[a-z]?)\)")


def data_dir() -> Path:
    return Path(get_setting("EVOLUTION_DATA_DIR", str(Path.home() / ".athena" / "evolution")))


def sentence_hash(text: str) -> str:
    return hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()


def cue_words(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in CONTRAST_CUES.finditer(text)})


def chunk_id(paper_id: UUID, position: int, text: str) -> UUID:
    """Stable across re-parses that produce the same chunk, so embeddings are not redone."""
    return uuid5(_CHUNK_NAMESPACE, f"{paper_id}|{position}|{sentence_hash(text)}")


def chunk_sentences(sentences: list[str], words: int = CHUNK_WORDS) -> list[str]:
    """Pack sentences into chunks of about ``words`` words; the last one may be short."""
    chunks, buf, count = [], [], 0
    for s in sentences:
        buf.append(s)
        count += len(s.split())
        if count >= words:
            chunks.append(" ".join(buf))
            buf, count = [], 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def s2_marked(snippet: str) -> tuple[str | None, str | None]:
    """(mention, marked sentence) for a Semantic Scholar snippet with exactly one citation marker.

    With several markers there is no telling which is the cited paper, so both are None.
    """
    markers = list(_MARKER.finditer(snippet))
    if len(markers) != 1:
        return None, None
    m = markers[0]
    return mention_before(snippet[:m.start()]), f"{snippet[:m.start()]}[[{m.group(0)}]]{snippet[m.end():]}"


# ── reference resolution ───────────────────────────────────────────────


@dataclass
class KnownPaper:
    id: UUID
    title: str
    year: int | None
    arxiv_id: str | None
    doi: str | None
    s2_paper_id: str | None = None


class PaperIndex:
    """Finds the known paper a bibliography entry or Semantic Scholar reference points to."""

    def __init__(self, papers: list[KnownPaper]):
        self.by_key: dict[str, UUID] = {}
        self.papers = {p.id: p for p in papers}
        for p in papers:
            for key in self._keys(p.arxiv_id, p.doi, p.title, p.s2_paper_id):
                self.by_key.setdefault(key, p.id)

    @staticmethod
    def _keys(arxiv_id, doi, title, s2_id=None) -> list[str]:
        keys = []
        if s2_id:
            keys.append(f"s2:{s2_id}")
        if arxiv_id:
            keys.append(f"arxiv:{_VERSION.sub('', arxiv_id)}")
        if doi:
            keys.append(f"doi:{doi.lower()}")
        key = title_key(title or "")
        if len(key) >= 15:  # short titles ("Fast R-CNN") only match through the fuzzy pass below
            keys.append(f"title:{key}")
        return keys

    def find(self, arxiv_id: str | None, doi: str | None, title: str, known_refs: list[UUID] = (),
             s2_id: str | None = None) -> UUID | None:
        for key in self._keys(arxiv_id, doi, title, s2_id):
            if key in self.by_key:
                return self.by_key[key]
        # Fuzzy, but only among papers a citation source already says this paper cites.
        for pid in known_refs:
            if pid in self.papers and same_title(title, self.papers[pid].title):
                return pid
        return None

    def find_bib(self, entry: BibEntry, known_refs: list[UUID]) -> UUID | None:
        return self.find(entry.arxiv_id or None, entry.doi or None, entry.title, known_refs)

    def find_s2(self, ref: S2Ref, known_refs: list[UUID]) -> UUID | None:
        return self.find(ref.arxiv_id, ref.doi, ref.title, known_refs, ref.paper_id)


# ── what one paper produces ────────────────────────────────────────────


@dataclass
class ContextRow:
    cited_id: UUID
    sentence: str
    section_type: str | None
    mention: str | None
    source: str
    marked: str | None = None   # the sentence with the cited paper's markers in [[ ]]
    s2_intents: list[str] = field(default_factory=list)


@dataclass
class FullTextResult:
    paper_id: UUID
    status: str                       # parsed | failed | s2_contexts
    sections: list[dict] = field(default_factory=list)
    chunks: list[dict] = field(default_factory=list)
    contexts: list[ContextRow] = field(default_factory=list)
    new_refs: set[UUID] = field(default_factory=set)  # cited papers no other source linked
    detail: dict = field(default_factory=dict)


def contexts_from_parse(paper_id: UUID, parsed: ParsedPaper, index: PaperIndex,
                        known_refs: list[UUID]) -> tuple[list[ContextRow], set[UUID], int]:
    resolved: dict[str, UUID] = {}
    for xml_id, entry in parsed.bib.items():
        pid = index.find_bib(entry, known_refs)
        if pid and pid != paper_id:
            resolved[xml_id] = pid
    rows = []
    for section in parsed.sections:
        for s in section.sentences:
            for xml_id in s.refs:
                if xml_id in resolved:
                    rows.append(ContextRow(resolved[xml_id], s.text, section.section_type, s.mentions.get(xml_id),
                                           "grobid", s.marked.get(xml_id)))
    return rows, set(resolved.values()) - set(known_refs), len(resolved)


def sections_and_chunks(paper_id: UUID, title: str, parsed: ParsedPaper) -> tuple[list[dict], list[dict]]:
    sections, chunks = [], []
    position = 0
    for i, section in enumerate(parsed.sections):
        section_id = uuid5(_CHUNK_NAMESPACE, f"{paper_id}|section|{i}")
        sections.append({"id": section_id, "paper_id": paper_id, "position": i, "heading": section.heading[:500],
                         "number": section.number, "section_type": section.section_type,
                         "rule_type": section.rule_type, "n_sentences": len(section.sentences)})
        for text in chunk_sentences([s.text for s in section.sentences]):
            chunks.append({"id": chunk_id(paper_id, position, text), "paper_id": paper_id, "section_id": section_id,
                           "position": position, "section_type": section.section_type, "text": text,
                           "n_words": len(text.split())})
            position += 1
    return sections, chunks


# ── fetching ───────────────────────────────────────────────────────────


@dataclass
class Tier2Paper:
    id: UUID
    openalex_id: str
    title: str
    arxiv_id: str | None
    oa_pdf_url: str | None
    s2_paper_id: str | None
    known_refs: list[UUID]


class FullTextFetcher:
    def __init__(self, grobid_url: str | None = None, root: Path | None = None, http: httpx.Client | None = None):
        self.grobid_url = (grobid_url or get_setting("GROBID_URL", "http://localhost:8070")).rstrip("/")
        self.root = root or data_dir()
        self.http = http or httpx.Client(timeout=300.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self._last_arxiv = 0.0

    def tei_path(self, paper: Tier2Paper) -> Path:
        return self.root / "tei" / f"{paper.openalex_id}.tei.xml"

    def pdf(self, paper: Tier2Paper) -> tuple[Path | None, str]:
        """A local PDF for ``paper`` and where it came from, or (None, reason)."""
        target = self.root / "pdfs" / f"{paper.openalex_id}.pdf"
        if target.exists() and target.stat().st_size > 10_000:
            return target, "cache"
        urls = []
        if paper.arxiv_id:
            urls.append(("arxiv", f"https://arxiv.org/pdf/{paper.arxiv_id}"))
        if paper.oa_pdf_url and "arxiv.org" not in paper.oa_pdf_url:
            urls.append(("oa", paper.oa_pdf_url))
        reason = "no open PDF"
        for source, url in urls:
            if source == "arxiv":
                wait = ARXIV_INTERVAL - (time.monotonic() - self._last_arxiv)
                if wait > 0:
                    time.sleep(wait)
                self._last_arxiv = time.monotonic()
            try:
                resp = self.http.get(url)
            except httpx.HTTPError as exc:
                reason = f"{source}: {type(exc).__name__}"
                continue
            if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(resp.content)
                return target, source
            reason = f"{source}: HTTP {resp.status_code}" if resp.status_code != 200 else f"{source}: not a PDF"
        return None, reason

    def grobid(self, pdf: Path) -> str:
        with open(pdf, "rb") as f:
            resp = self.http.post(
                f"{self.grobid_url}/api/processFulltextDocument",
                files={"input": (pdf.name, f, "application/pdf")},
                # Consolidation calls CrossRef; references are resolved against Athena's papers instead.
                data={"segmentSentences": "1", "consolidateHeader": "0", "consolidateCitations": "0"},
            )
        resp.raise_for_status()
        return resp.text

    def check_grobid(self) -> None:
        try:
            self.http.get(f"{self.grobid_url}/api/isalive", timeout=10).raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"GROBID is not reachable at {self.grobid_url}. Start it with "
                "`docker run -d --name athena-grobid -p 8070:8070 grobid/grobid:0.9.1-crf`."
            ) from exc


def process_papers(papers: list[Tier2Paper], index: PaperIndex, fetcher: FullTextFetcher,
                   s2: SemanticScholarClient | None, reparse: bool = False) -> list[FullTextResult]:
    """Fetch and parse each paper; papers without an open PDF fall back to Semantic Scholar contexts."""
    fetcher.check_grobid()
    tei: dict[UUID, str] = {}
    pdfs: dict[UUID, Path] = {}
    missing: dict[UUID, str] = {}
    for i, paper in enumerate(papers, 1):
        path = fetcher.tei_path(paper)
        if path.exists() and not reparse:
            tei[paper.id] = path.read_text(encoding="utf-8")
            continue
        pdf, source = fetcher.pdf(paper)
        if pdf is None:
            missing[paper.id] = source
        else:
            pdfs[paper.id] = pdf
        if i % 25 == 0:
            logger.info(f"Full text: checked {i}/{len(papers)} papers ({len(pdfs)} PDFs to parse)")

    def run_grobid(item):
        pid, pdf = item
        try:
            return pid, fetcher.grobid(pdf), None
        except httpx.HTTPError as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else ""
            return pid, None, f"grobid: {type(exc).__name__} {status}".strip()

    by_id = {p.id: p for p in papers}
    with ThreadPoolExecutor(max_workers=GROBID_WORKERS) as pool:
        for pid, text, error in pool.map(run_grobid, pdfs.items()):
            if text is None:
                missing[pid] = error
                continue
            path = fetcher.tei_path(by_id[pid])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            tei[pid] = text
    logger.info(f"Full text: {len(tei)} parsed, {len(missing)} without full text")

    results = []
    for paper in papers:
        if paper.id in tei:
            results.append(_from_tei(paper, tei[paper.id], index))
        else:
            results.append(_from_s2(paper, index, s2, missing.get(paper.id, "unknown")))
    return results


def _from_tei(paper: Tier2Paper, tei: str, index: PaperIndex) -> FullTextResult:
    try:
        parsed = parse_tei(tei, named_method(paper.title))
    except Exception as exc:  # lxml raises several error types on malformed TEI
        return FullTextResult(paper.id, "failed", detail={"error": f"TEI: {type(exc).__name__}"})
    if not any(s.section_type != "abstract" for s in parsed.sections):
        return FullTextResult(paper.id, "failed", detail={"error": "no body text"})
    sections, chunks = sections_and_chunks(paper.id, paper.title, parsed)
    contexts, new_refs, resolved = contexts_from_parse(paper.id, parsed, index, paper.known_refs)
    detail = {"sections": len(sections), "chunks": len(chunks), "contexts": len(contexts), "bib": len(parsed.bib),
              "bib_resolved": resolved, "fallback_links": parsed.fallback_links,
              "dropped_sentences": parsed.dropped_sentences}
    return FullTextResult(paper.id, "parsed", sections, chunks, contexts, new_refs, detail)


def _from_s2(paper: Tier2Paper, index: PaperIndex, s2: SemanticScholarClient | None, reason: str) -> FullTextResult:
    if s2 is None or not paper.s2_paper_id:
        return FullTextResult(paper.id, "failed", detail={"error": reason})
    try:
        contexts = s2.reference_contexts(paper.s2_paper_id)
    except (httpx.HTTPError, SemanticScholarAuthError) as exc:
        logger.warning(f"Semantic Scholar contexts for {paper.openalex_id} failed: {exc}")
        return FullTextResult(paper.id, "failed", detail={"error": f"{reason}; s2: {type(exc).__name__}"})
    rows = []
    for ctx in contexts:
        cited = index.find_s2(ctx.cited, paper.known_refs)
        if cited is None or cited == paper.id:
            continue
        for snippet in ctx.contexts:
            mention, marked = s2_marked(snippet.strip())
            rows.append(ContextRow(cited, snippet.strip(), None, mention, "s2", marked, ctx.intents))
    return FullTextResult(paper.id, "s2_contexts", contexts=rows,
                          detail={"error": reason, "contexts": len(rows)})


def run_full_text(slug: str, reparse: bool = False, limit: int | None = None,
                  fetcher: FullTextFetcher | None = None, s2: SemanticScholarClient | None = None) -> dict:
    """Fetch, parse and store full text for a topic's Tier 2 papers that do not have it yet."""
    from collections import Counter

    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}")
        config = TopicConfig.from_dict(topic.config)
        ids = db.tier2_ids(session, topic, config.tier2_successors)
        papers = db.tier2_papers(session, ids, reparse)[:limit]
        index = PaperIndex(db.known_papers(session))
    logger.info(f"{slug}: {len(ids)} Tier 2 papers, {len(papers)} to process")
    fetcher = fetcher or FullTextFetcher()
    s2 = s2 or SemanticScholarClient()
    statuses: Counter = Counter()
    contexts = new_refs = 0
    stale: list[UUID] = []
    for start in range(0, len(papers), BATCH):
        for result in process_papers(papers[start:start + BATCH], index, fetcher, s2, reparse):
            stale += db.save_full_text(result)
            statuses[result.status] += 1
            contexts += len(result.contexts)
            new_refs += len(result.new_refs)
        logger.info(f"{slug}: {min(start + BATCH, len(papers))}/{len(papers)} done, {dict(statuses)}")
    if stale:
        from athena.evolution.vectors import delete_points
        delete_points(stale)
    return {"tier2": len(ids), "processed": len(papers), **statuses, "contexts": contexts,
            "edges_from_grobid": new_refs, "stale_vectors_removed": len(stale)}
