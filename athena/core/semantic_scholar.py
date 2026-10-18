"""
Semantic Scholar client: the second citation source.

OpenAlex has no reference lists for many recent arXiv preprints (QLoRA,
AdaLoRA and DoRA list zero references) and undercounts their citations
(QLoRA: 500 in OpenAlex, about 5,900 here). Semantic Scholar extracts
references from the PDFs, so it fills both gaps, and it also has the
sentences in which one paper cites another ("contexts").

The free API allows one request per second with a key (request one at
semanticscholar.org/product/api#api-key-form) and shares a small pool
between all keyless callers. The limit is the key's, not a process's, so
every process takes its turn from one slot kept in Redis. 429s still come
(also when the service is busy), so they are retried with backoff.
Responses are cached on disk per paper, so a rebuild only asks for papers
it has not seen.

Every Semantic Scholar call in Athena goes through this client: map builds,
full text, method names, feed links, citation momentum, the enricher at
ingest and live search.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from loguru import logger
from tenacity import Retrying, retry_if_exception, stop_after_attempt, stop_after_delay, wait_exponential

from athena.core.config_store import get_setting

BASE_URL = "https://api.semanticscholar.org/graph/v1"
BATCH_SIZE = 200          # the API takes 500, but nested reference lists push responses toward its 10 MB cap
CONTEXT_PAGE = 1000
CACHE_TTL_SECONDS = 30 * 24 * 3600
MIN_INTERVAL_KEY = 1.1    # seconds between requests: keys are limited to one per second
MIN_INTERVAL_NO_KEY = 3.0
PATIENCE = 900            # seconds a request may spend waiting out rate limits
SLOT_KEY = "s2:next_slot"
# Reserves the next request slot for every process at once: returns how many milliseconds to wait. Uses the
# Redis server's clock, so processes whose clocks differ still agree.
_SLOT_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local at = math.max(now, tonumber(redis.call('GET', KEYS[1]) or '0'))
local gap = tonumber(ARGV[1])
redis.call('SET', KEYS[1], at + gap, 'PX', at + gap - now + 60000)
return at - now
"""
_REF_FIELDS = ["paperId", "externalIds", "title", "year"]
PAPER_FIELDS = ",".join(["paperId", "externalIds", "title", "year", "citationCount", "referenceCount"]
                        + [f"references.{f}" for f in _REF_FIELDS])
CANDIDATE_FIELDS = PAPER_FIELDS + ",abstract,venue,publicationTypes"
CONTEXT_FIELDS = ",".join(["contexts", "intents", "isInfluential", *_REF_FIELDS])
CITATION_CONTEXT_FIELDS = "contexts,paperId"
CITATION_PAGE = 1000  # the citations endpoint's largest page
CITATION_OFFSET_MAX = 9000  # offset + limit may not pass 10,000
CITATION_DATE_FIELDS = "publicationDate"
SEARCH_FIELDS = "paperId,externalIds,title,year,citationCount,abstract,venue,publicationTypes"
RELEVANCE_FIELDS = "paperId,title,abstract,year,authors,citationCount,url"


class SemanticScholarAuthError(RuntimeError):
    """The API key was rejected (403), or there is none and the caller will not use the keyless pool."""


@dataclass
class S2Ref:
    paper_id: str | None
    title: str
    year: int | None
    arxiv_id: str | None = None
    doi: str | None = None
    mag_id: str | None = None

    @classmethod
    def from_api(cls, raw: dict) -> "S2Ref":
        ext = raw.get("externalIds") or {}
        return cls(paper_id=raw.get("paperId"), title=(raw.get("title") or "").strip(), year=raw.get("year"),
                   arxiv_id=ext.get("ArXiv"), doi=(ext.get("DOI") or "").lower() or None,
                   mag_id=str(ext["MAG"]) if ext.get("MAG") else None)


@dataclass
class S2Paper(S2Ref):
    citation_count: int = 0
    reference_count: int = 0
    references: list[S2Ref] = field(default_factory=list)
    abstract: str | None = None
    venue: str | None = None
    publication_types: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "S2Paper":
        base = S2Ref.from_api(raw)
        return cls(**vars(base), citation_count=raw.get("citationCount") or 0,
                   reference_count=raw.get("referenceCount") or 0,
                   references=[S2Ref.from_api(r) for r in (raw.get("references") or []) if r],
                   abstract=raw.get("abstract"), venue=raw.get("venue") or None,
                   publication_types=raw.get("publicationTypes") or [])


@dataclass
class S2Context:
    """Where the citing paper cites ``cited``: its sentences and Semantic Scholar's intent labels."""
    cited: S2Ref
    contexts: list[str]
    intents: list[str]
    is_influential: bool


def lookup_id(arxiv_id: str | None = None, doi: str | None = None, openalex_id: str | None = None) -> str | None:
    """The best Semantic Scholar identifier for a paper: arXiv ID, then DOI, then MAG ID.

    OpenAlex kept Microsoft Academic Graph IDs for works it inherited, so 'W2194775991' is MAG 2194775991.
    Works OpenAlex created itself start at W4200000000.
    """
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"
    if doi:
        return f"DOI:{doi}"
    if openalex_id and openalex_id[1:].isdigit() and int(openalex_id[1:]) < 4_200_000_000:
        return f"MAG:{openalex_id[1:]}"
    return None


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class SemanticScholarClient:
    def __init__(self, api_key: str | None = None, cache_dir: str | None = None, http: httpx.Client | None = None,
                 min_interval: float | None = None, keyless_ok: bool = True, patience: float = PATIENCE):
        self.api_key = api_key if api_key is not None else get_setting("SEMANTIC_SCHOLAR_API_KEY")
        # False: no key, or a rejected one, raises SemanticScholarAuthError instead of using the slow shared pool.
        self.keyless_ok = keyless_ok
        if not self.api_key and not keyless_ok:
            raise SemanticScholarAuthError("no Semantic Scholar API key")
        if cache_dir is None:
            cache_dir = get_setting("S2_CACHE_DIR", str(Path.home() / ".athena" / "s2_cache"))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=120.0, headers=headers)
        if min_interval is None:
            min_interval = MIN_INTERVAL_KEY if self.api_key else MIN_INTERVAL_NO_KEY
        self.min_interval = min_interval
        # How long one request may wait out rate limits: a person waiting on live search gets seconds, not minutes.
        self.patience = patience
        self._shared_slots = True  # off after Redis fails once; then this process paces itself
        self._last_request = 0.0
        self.requests = 0
        self.cache_hits = 0
        self.rate_limited = 0

    # ── public API ──────────────────────────────────────────────────

    def get_papers(self, ids: list[str], fields: str = PAPER_FIELDS,
                   max_age: float | None = None) -> dict[str, S2Paper | None]:
        """Papers by Semantic Scholar identifier ('ARXIV:2106.09685', 'DOI:...', 'MAG:...').

        Unknown identifiers map to None. Each paper is cached separately, so asking again for a
        slightly different set only fetches the new ones. ``max_age`` (seconds) refetches papers cached
        longer ago, for new preprints whose references Semantic Scholar has not extracted yet.
        """
        out: dict[str, S2Paper | None] = {}
        missing = []
        for pid in dict.fromkeys(i for i in ids if i):
            cached = self._cache_read("paper", pid, fields, max_age)
            if cached is not None:
                out[pid] = S2Paper.from_api(cached["data"]) if cached["data"] else None
            else:
                missing.append(pid)
        for start in range(0, len(missing), BATCH_SIZE):
            chunk = missing[start:start + BATCH_SIZE]
            data = self._request("POST", "/paper/batch", {"fields": fields}, {"ids": chunk})
            for pid, raw in zip(chunk, data or [None] * len(chunk)):
                self._cache_write("paper", pid, fields, raw)
                out[pid] = S2Paper.from_api(raw) if raw else None
        return out

    def search_bulk(self, query: str, limit: int, fields_of_study: str = "Computer Science") -> list[S2Paper]:
        """Papers matching a boolean query ('"low-rank adaptation" | lora'), most cited first.

        Bulk search returns up to 1,000 papers per request. It is how a topic finds papers its seeds'
        citation lists cannot reach: the citations endpoint lists newest first and stops at 10,000,
        so for LoRA (24,000 citers) it never gets back to 2023.
        """
        key = json.dumps([query, fields_of_study])
        cached = self._cache_read("search", key, SEARCH_FIELDS)
        rows = cached["data"] if cached is not None else []
        if cached is None or (len(rows) < limit and cached.get("more")):
            rows, token = [], None
            while len(rows) < limit:
                params = {"query": query, "sort": "citationCount:desc", "fields": SEARCH_FIELDS}
                if fields_of_study:
                    params["fieldsOfStudy"] = fields_of_study
                if token:
                    params["token"] = token
                data = self._request("GET", "/paper/search/bulk", params) or {}
                rows += data.get("data") or []
                token = data.get("token")
                if not token:
                    break
            path = self._cache_file("search", key, SEARCH_FIELDS)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"fetched_at": time.time(), "data": rows, "more": bool(token)}))
        return [S2Paper.from_api(r) for r in rows[:limit]]

    def search(self, query: str, limit: int = 15, fields: str = RELEVANCE_FIELDS) -> list[dict]:
        """The papers most relevant to ``query``, as the API returns them. Not cached: live search wants today's."""
        data = self._request("GET", "/paper/search", {"query": query, "fields": fields, "limit": limit}) or {}
        return data.get("data") or []

    def reference_contexts(self, paper_id: str) -> list[S2Context]:
        """Every reference of ``paper_id`` with the sentences that cite it."""
        cached = self._cache_read("contexts", paper_id, CONTEXT_FIELDS)
        if cached is not None:
            rows = cached["data"]
        else:
            rows, offset = [], 0
            while True:
                data = self._request("GET", f"/paper/{paper_id}/references",
                                     {"fields": CONTEXT_FIELDS, "limit": CONTEXT_PAGE, "offset": offset})
                if not data:
                    break
                rows += data.get("data") or []
                if data.get("next") is None:
                    break
                offset = data["next"]
            self._cache_write("contexts", paper_id, CONTEXT_FIELDS, rows)
        return [S2Context(cited=S2Ref.from_api(r.get("citedPaper") or {}), contexts=r.get("contexts") or [],
                          intents=r.get("intents") or [], is_influential=bool(r.get("isInfluential")))
                for r in rows if r.get("citedPaper")]

    def citation_contexts(self, paper_id: str, limit: int = CITATION_PAGE) -> list[tuple[str, list[str]]]:
        """(citing paper, sentences citing ``paper_id``) for up to ``limit`` citing papers, newest first.

        One request per paper: enough to see what name recent papers use for it (the method-name feature).
        """
        key = f"{paper_id}:{limit}"
        cached = self._cache_read("citations", key, CITATION_CONTEXT_FIELDS)
        if cached is not None:
            rows = cached["data"]
        else:
            data = self._request("GET", f"/paper/{paper_id}/citations",
                                 {"fields": CITATION_CONTEXT_FIELDS, "limit": min(limit, CITATION_PAGE)})
            rows = (data or {}).get("data") or []
            self._cache_write("citations", key, CITATION_CONTEXT_FIELDS, rows)
        return [((r.get("citingPaper") or {}).get("paperId") or "", r.get("contexts") or []) for r in rows]

    def citation_dates(self, paper_id: str, max_age: float | None = None) -> list[str | None]:
        """The publication date ('YYYY-MM-DD') of each paper citing ``paper_id``, None where it has none.

        Pages through every citing paper the endpoint serves (it stops at 10,000), for citation-momentum history.
        """
        cached = self._cache_read("citation_dates", paper_id, CITATION_DATE_FIELDS, max_age)
        if cached is not None:
            return cached["data"]
        dates, offset = [], 0
        while offset < CITATION_OFFSET_MAX:
            data = self._request("GET", f"/paper/{paper_id}/citations",
                                 {"fields": CITATION_DATE_FIELDS, "limit": CITATION_PAGE, "offset": offset})
            if not data:
                break
            dates += [(r.get("citingPaper") or {}).get("publicationDate") for r in data.get("data") or []]
            if data.get("next") is None:
                break
            offset = data["next"]
        self._cache_write("citation_dates", paper_id, CITATION_DATE_FIELDS, dates)
        return dates

    # ── transport ───────────────────────────────────────────────────

    def _cache_file(self, kind: str, key: str, fields: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(json.dumps([kind, key, fields]).encode()).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.json"

    def _cache_read(self, kind: str, key: str, fields: str, max_age: float | None = None) -> dict | None:
        path = self._cache_file(kind, key, fields)
        if path and path.exists():
            entry = json.loads(path.read_text())
            if time.time() - entry["fetched_at"] < min(CACHE_TTL_SECONDS, max_age or CACHE_TTL_SECONDS):
                self.cache_hits += 1
                return entry
        return None

    def _cache_write(self, kind: str, key: str, fields: str, data) -> None:
        path = self._cache_file(kind, key, fields)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": time.time(), "data": data}))

    def _request(self, method: str, path: str, params: dict, body: dict | None = None):
        try:
            return self._send(method, path, params, body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403:
                raise
            if not self.api_key:
                raise SemanticScholarAuthError("Semantic Scholar refused the request (403) without a key") from exc
            if not self.keyless_ok:
                raise SemanticScholarAuthError("the Semantic Scholar API key was rejected") from exc
            # An expired or revoked key gets 403 on every call, while the keyless pool still answers.
            logger.warning("Semantic Scholar rejected the API key (403); continuing without it, more slowly. "
                           "Replace SEMANTIC_SCHOLAR_API_KEY in the Settings page.")
            self.api_key = ""
            self.http.headers.pop("x-api-key", None)
            self.min_interval = max(self.min_interval, MIN_INTERVAL_NO_KEY)
            return self._request(method, path, params, body)

    # The keyless pool is shared by everyone and can refuse for minutes at a time, so rate limits are
    # waited out for up to ``patience`` seconds (15 minutes by default) rather than a fixed number of attempts.
    def _send(self, method: str, path: str, params: dict, body: dict | None):
        retrying = Retrying(retry=retry_if_exception(_is_transient),
                            wait=wait_exponential(multiplier=2, min=min(4, max(1, self.patience / 5)), max=90),
                            stop=stop_after_attempt(40) | stop_after_delay(self.patience), reraise=True)
        return retrying(self._send_once, method, path, params, body)

    def _send_once(self, method: str, path: str, params: dict, body: dict | None):
        self._pace()
        resp = self.http.request(method, path, params=params, json=body)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            self.rate_limited += 1
            logger.debug(f"Semantic Scholar rate limit on {path}; backing off")
        resp.raise_for_status()
        self.requests += 1
        return resp.json()

    def _pace(self) -> None:
        """Wait for this request's turn: the next slot shared by every process, else this process's own."""
        if self.min_interval <= 0:
            return
        wait = None
        if self._shared_slots:
            try:
                from athena.core.redis_client import get_redis
                wait = get_redis().eval(_SLOT_SCRIPT, 1, SLOT_KEY, int(self.min_interval * 1000)) / 1000
            except Exception as exc:  # no Redis (a script, a test): pace this process alone
                logger.debug(f"Semantic Scholar: no shared request slots ({exc}); pacing this process only")
                self._shared_slots = False
        if wait is None:
            wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
