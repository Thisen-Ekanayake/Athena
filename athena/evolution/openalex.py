"""
OpenAlex client for building topic corpora.

Costs (OpenAlex pricing as of 2026): single-record lookups by ID or DOI are
free, list and filter calls cost $0.0001 each, and keyword or semantic
searches $0.001. The free allowance is $0.10/day without a key and $1/day
with a free key from openalex.org/settings/api. Responses are cached on disk
so rebuilding a topic does not spend the allowance twice.

OpenAlex metadata for ML preprints is imperfect: LoRA's arXiv DOI resolves
to a record titled "LoRA Fine-Tuning of a 3B Code LLM for Algorithmic
Efficiency", and the Transformer paper is dated 2025. Callers repair years
(see ``athena.evolution.corpus``) and take seed titles from the topic config.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from athena.core.config_store import get_setting

BASE_URL = "https://api.openalex.org"
PER_PAGE = 200
IDS_PER_FILTER = 100
DOIS_PER_FILTER = 50
CACHE_TTL_SECONDS = 30 * 24 * 3600
WORK_FIELDS = ",".join([
    "id", "doi", "display_name", "publication_year", "type", "cited_by_count", "referenced_works",
    "authorships", "primary_location", "best_oa_location", "locations", "open_access", "primary_topic",
    "abstract_inverted_index",
])


# OpenAlex's 26 fields (primary_topic.field). Filters take the ID: several names contain commas, which
# would split a filter value.
FIELD_IDS = {
    "Agricultural and Biological Sciences": 11, "Arts and Humanities": 12,
    "Biochemistry, Genetics and Molecular Biology": 13, "Business, Management and Accounting": 14,
    "Chemical Engineering": 15, "Chemistry": 16, "Computer Science": 17, "Decision Sciences": 18,
    "Earth and Planetary Sciences": 19, "Economics, Econometrics and Finance": 20, "Energy": 21, "Engineering": 22,
    "Environmental Science": 23, "Immunology and Microbiology": 24, "Materials Science": 25, "Mathematics": 26,
    "Medicine": 27, "Neuroscience": 28, "Nursing": 29, "Pharmacology, Toxicology and Pharmaceutics": 30,
    "Physics and Astronomy": 31, "Psychology": 32, "Social Sciences": 33, "Veterinary": 34, "Dentistry": 35,
    "Health Professions": 36,
}
SEMANTIC_MAX = 50  # search.semantic returns at most 50 works


class OpenAlexBudgetError(RuntimeError):
    """The daily OpenAlex allowance is used up."""


def short_id(value: str | None) -> str:
    """'https://openalex.org/W2626778328' -> 'W2626778328'."""
    return value.rsplit("/", 1)[-1] if value else ""


_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?/?$", re.IGNORECASE)


def arxiv_id_from(raw: dict) -> str | None:
    """Find an arXiv ID in a work's DOI or any of its locations."""
    match = _ARXIV_DOI.search(raw.get("doi") or "")
    if match:
        return match.group(1)
    locations = [raw.get("best_oa_location"), raw.get("primary_location"), *(raw.get("locations") or [])]
    for loc in locations:
        for key in ("landing_page_url", "pdf_url"):
            match = _ARXIV_URL.search((loc or {}).get(key) or "")
            if match:
                return match.group(1)
    return None


def search_expression(terms: list[str]) -> str:
    """Terms for a ``.search`` filter, any of them: '"mixture of experts" OR moe'.

    Phrases are quoted; commas and other punctuation are dropped, since a comma would end the filter.
    """
    parts = []
    for term in terms:
        clean = " ".join(re.sub(r"[^\w\s-]", " ", term.lower()).split())
        if clean:
            parts.append(f'"{clean}"' if re.search(r"[\s-]", clean) else clean)
    return " OR ".join(dict.fromkeys(parts))


def _field_filter(fields: list[str] | None) -> str:
    ids = [str(FIELD_IDS[f]) for f in fields or [] if f in FIELD_IDS]
    return f",primary_topic.field.id:{'|'.join(ids)}" if ids else ""


def arxiv_year(arxiv_id: str | None) -> int | None:
    """Submission year encoded in an arXiv ID: '2106.09685' -> 2021, 'cs/0102001' -> 2001."""
    if not arxiv_id:
        return None
    match = re.match(r"(\d{2})(\d{2})\.\d{4,5}", arxiv_id)
    if match:
        return 2000 + int(match.group(1))
    match = re.search(r"/(\d{2})\d{5}", arxiv_id)
    if match:
        yy = int(match.group(1))
        return 1900 + yy if yy >= 91 else 2000 + yy
    return None


def reconstruct_abstract(inverted: dict | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not inverted:
        return None
    positions = sorted((pos, word) for word, poss in inverted.items() for pos in poss)
    return " ".join(word for _, word in positions) or None


@dataclass
class Work:
    openalex_id: str
    title: str
    year: int | None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    work_type: str | None = None
    venue: str | None = None
    authors: list[str] = field(default_factory=list)
    cited_by_count: int = 0
    referenced_works: list[str] = field(default_factory=list)
    is_oa: bool = False
    oa_pdf_url: str | None = None
    primary_topic: str | None = None
    field_name: str | None = None
    # Filled from Semantic Scholar by ``athena.evolution.corpus.augment_with_s2``.
    s2_paper_id: str | None = None
    s2_cited_by_count: int | None = None
    s2_refs: list[str] = field(default_factory=list)  # OpenAlex IDs of references found through Semantic Scholar

    @property
    def citations(self) -> int:
        """Global citations: the larger of the two sources' counts, since each misses some."""
        return max(self.cited_by_count, self.s2_cited_by_count or 0)

    @classmethod
    def from_api(cls, raw: dict) -> "Work":
        topic = raw.get("primary_topic") or {}
        best_oa = raw.get("best_oa_location") or {}
        source = (raw.get("primary_location") or {}).get("source") or {}
        doi = raw.get("doi")
        return cls(
            openalex_id=short_id(raw.get("id")),
            title=(raw.get("display_name") or "").strip(),
            year=raw.get("publication_year"),
            doi=doi.replace("https://doi.org/", "") if doi else None,
            arxiv_id=arxiv_id_from(raw),
            abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
            work_type=raw.get("type"),
            venue=source.get("display_name"),
            authors=[(a.get("author") or {}).get("display_name", "") for a in (raw.get("authorships") or [])][:10],
            cited_by_count=raw.get("cited_by_count") or 0,
            referenced_works=[short_id(r) for r in (raw.get("referenced_works") or [])],
            is_oa=bool((raw.get("open_access") or {}).get("is_oa")),
            oa_pdf_url=best_oa.get("pdf_url") or (raw.get("open_access") or {}).get("oa_url"),
            primary_topic=topic.get("display_name"),
            field_name=(topic.get("field") or {}).get("display_name"),
        )


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("message") or body.get("error") or "")[:300]
    except ValueError:
        return resp.text[:300]


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class OpenAlexClient:
    def __init__(self, api_key: str | None = None, mailto: str | None = None, cache_dir: str | None = None,
                 http: httpx.Client | None = None):
        self.api_key = api_key if api_key is not None else get_setting("OPENALEX_API_KEY")
        self.mailto = mailto if mailto is not None else get_setting("OPENALEX_MAILTO")
        if cache_dir is None:
            cache_dir = get_setting("OPENALEX_CACHE_DIR", str(Path.home() / ".athena" / "openalex_cache"))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=60.0)
        self.spent_usd = 0.0
        self.requests = 0  # network requests, free lookups included; spent_usd has the cost
        self.cache_hits = 0

    # ── public API ──────────────────────────────────────────────────

    def get_work(self, identifier: str) -> Work | None:
        """One work by OpenAlex ID ('W123') or DOI ('doi:10.48550/arxiv.2106.09685'). Free."""
        data = self._get(f"/works/{identifier}", {"select": WORK_FIELDS})
        return Work.from_api(data) if data.get("id") else None

    def get_works(self, ids: list[str]) -> list[Work]:
        """Many works by OpenAlex ID, 100 per list call. Merged or deleted IDs are silently missing."""
        works: list[Work] = []
        unique = list(dict.fromkeys(i for i in ids if i))
        for start in range(0, len(unique), IDS_PER_FILTER):
            chunk = unique[start:start + IDS_PER_FILTER]
            data = self._get("/works", {"filter": "openalex:" + "|".join(chunk), "per-page": IDS_PER_FILTER,
                                        "select": WORK_FIELDS})
            works += [Work.from_api(raw) for raw in data.get("results", [])]
        return works

    def get_works_by_doi(self, dois: list[str]) -> list[Work]:
        """Many works by DOI, 50 per list call (DOIs are long, so fewer fit in a URL than IDs)."""
        works: list[Work] = []
        unique = list(dict.fromkeys(d.lower() for d in dois if d))
        for start in range(0, len(unique), DOIS_PER_FILTER):
            chunk = unique[start:start + DOIS_PER_FILTER]
            data = self._get("/works", {"filter": "doi:" + "|".join(chunk), "per-page": DOIS_PER_FILTER,
                                        "select": WORK_FIELDS})
            works += [Work.from_api(raw) for raw in data.get("results", [])]
        return works

    def search_title(self, title: str, limit: int = 10) -> list[Work]:
        """Works whose title matches, most cited first. Costs $0.001 (ten list calls)."""
        query = re.sub(r"[^\w\s-]", " ", title)  # commas would split the filter
        data = self._get("/works", {"filter": f"title.search:{query}", "sort": "cited_by_count:desc",
                                    "per-page": limit, "select": WORK_FIELDS})
        return [Work.from_api(raw) for raw in data.get("results", [])]

    def citing_works(self, work_id: str, limit: int) -> list[Work]:
        """The ``limit`` most-cited works that cite ``work_id``."""
        works: list[Work] = []
        page = 1
        while len(works) < limit:
            per_page = min(PER_PAGE, limit - len(works))
            data = self._get("/works", {"filter": f"cites:{work_id}", "sort": "cited_by_count:desc",
                                        "per-page": per_page, "page": page, "select": WORK_FIELDS})
            batch = [Work.from_api(raw) for raw in data.get("results", [])]
            works += batch
            if len(batch) < per_page:
                break
            page += 1
        return works

    def search_works(self, terms: list[str], limit: int, fields: list[str] | None = None,
                     in_title: bool = False) -> list[Work]:
        """The ``limit`` most-cited works whose title and abstract (or only title) match any of ``terms``.

        Each page of 200 is one search call ($0.001). ``fields`` are OpenAlex field names; empty means any.
        """
        expression = search_expression(terms)
        if not expression or limit <= 0:
            return []
        kind = "title.search" if in_title else "title_and_abstract.search"
        works: list[Work] = []
        page = 1
        while len(works) < limit:
            per_page = min(PER_PAGE, limit - len(works))
            data = self._get("/works", {"filter": f"{kind}:{expression}{_field_filter(fields)}",
                                        "sort": "cited_by_count:desc", "per-page": per_page, "page": page,
                                        "select": WORK_FIELDS})
            batch = [Work.from_api(raw) for raw in data.get("results", [])]
            works += batch
            if len(batch) < per_page:
                break
            page += 1
        return works

    def semantic_search(self, query: str, limit: int = SEMANTIC_MAX) -> list[Work]:
        """Works whose title and abstract are nearest ``query`` in OpenAlex's embedding space ($0.001).

        Finds papers that never use the query's words (Switch Transformer for "mixture of experts").
        It takes no field filter, so callers filter by field themselves. Best effort: the endpoint is
        newer than the rest, so a failure returns nothing.
        """
        params = {"search.semantic": query[:2000], "per-page": min(limit, SEMANTIC_MAX), "select": WORK_FIELDS}
        try:
            data = self._get("/works", params)
        except httpx.HTTPError as exc:
            logger.warning(f"OpenAlex semantic search failed: {exc}")
            return []
        return [Work.from_api(raw) for raw in data.get("results", [])]

    def field_counts(self, terms: list[str]) -> list[tuple[str, int]]:
        """How many works matching ``terms`` (title and abstract) fall in each field, largest first ($0.001)."""
        expression = search_expression(terms)
        if not expression:
            return []
        data = self._get("/works", {"filter": f"title_and_abstract.search:{expression}",
                                    "group_by": "primary_topic.field.id"})
        groups = [(g.get("key_display_name") or "", int(g.get("count") or 0)) for g in data.get("group_by", [])]
        return sorted([g for g in groups if g[0] and g[1] > 0], key=lambda g: -g[1])

    # ── transport ───────────────────────────────────────────────────

    def _get(self, path: str, params: dict) -> dict:
        cache_file = self._cache_file(path, params)
        if cache_file and cache_file.exists():
            entry = json.loads(cache_file.read_text())
            if time.time() - entry["fetched_at"] < CACHE_TTL_SECONDS:
                self.cache_hits += 1
                return entry["data"]
        data = self._fetch(path, params)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"fetched_at": time.time(), "data": data}))
        return data

    def _cache_file(self, path: str, params: dict) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(json.dumps([path, sorted(params.items())]).encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    @retry(retry=retry_if_exception(_is_transient), wait=wait_exponential(multiplier=1, max=30),
           stop=stop_after_attempt(5), reraise=True)
    def _fetch(self, path: str, params: dict) -> dict:
        query = dict(params)
        if self.api_key:
            query["api_key"] = self.api_key
        if self.mailto:
            query["mailto"] = self.mailto
        resp = self.http.get(path, params=query)
        remaining = resp.headers.get("x-ratelimit-remaining-usd")
        if resp.status_code == 429 and remaining is not None and float(remaining) <= 0:
            raise OpenAlexBudgetError(
                "OpenAlex daily allowance used up. Set OPENALEX_API_KEY (free at openalex.org/settings/api) "
                "for $1/day instead of $0.10/day, or wait for the reset."
            )
        if resp.status_code == 404:
            return {}
        if resp.is_error:
            # Not raise_for_status(): its message carries the URL, and with it the API key, into logs and
            # into a failed topic's status_detail, which the UI shows.
            raise httpx.HTTPStatusError(f"OpenAlex answered {resp.status_code} for {path}: {_error_text(resp)}",
                                        request=resp.request, response=resp)
        self.requests += 1
        self.spent_usd += float(resp.headers.get("x-ratelimit-cost-usd") or 0)
        if remaining is not None and float(remaining) < 0.01:
            logger.warning(f"OpenAlex allowance nearly used up: ${float(remaining):.4f} left today")
        return resp.json()
