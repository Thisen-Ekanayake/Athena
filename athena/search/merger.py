"""Merge library and live search results into one deduplicated list, ranked by relevance rather than by source.

The library used to come first: on a feed of the last month's papers it filled the whole list ("40 from Athena's
library, 28 from Semantic Scholar and arXiv" showed 40 library items), so a search for a known 2023 paper never
showed it (feedback 2026-11-07). Now:

- library hits must be relevant (``relevant_local``): a similarity of at least ``LOCAL_FLOOR``, or a title or
  keyword match; the meaning side otherwise returns its 50 nearest items however far they are;
- the two lists are taken in turns, each in its own relevance order, the live one first: it searches the whole
  literature, the library a few weeks of feed;
- library hits found by meaning alone fill at most ``LIBRARY_SHARE`` of the list. Similarity does not tell a near
  miss from a hit there: for "hallucination detection in machine translation" a meta-study of LLM hallucination
  detection scored 0.658 and an MT evaluation paper 0.624 (2026-11-08);
- a paper whose title is the query, shares a long phrase with it, or carries a name the query uses ("HalOmi",
  "NLLB-200") leads.
"""
from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
LOCAL_FLOOR = 0.6   # library hits below this similarity are off topic (relevant ones score 0.6-0.8)
CONTAINS_MAX_WORDS = 8   # a longer query is a question: it is not looked for inside titles
PASTED_SHARE = 0.6       # a title found inside the query must be this share of its words
PHRASE_WORDS = 3         # a phrase of this many words shared with a title, half the query or more, is a title match
LIBRARY_SHARE = 1 / 3    # of the list, for library hits found by meaning alone
FILLER = {"a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "with", "by", "from", "at", "via", "is", "are"}
# Words that look like names but are not: acronyms every paper in a field uses.
COMMON_NAMES = {"ai", "ml", "nlp", "llm", "llms", "nmt", "mt", "asr", "tts", "cv", "rl", "gpu", "api", "qa", "ner",
                "pos", "bert", "gpt", "vqa", "rag", "lora"}


def _normalise_title(title: str | None) -> str:
    if not title:
        return ""
    lowered = title.lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()


def interleave(*ranked: list[dict]) -> list[dict]:
    """Several sources' results, each in its own relevance order, taken in turns: 1st of each, then 2nd, ..."""
    out = []
    for i in range(max((len(r) for r in ranked), default=0)):
        out.extend(r[i] for r in ranked if i < len(r))
    return out


def names(query: str) -> set[str]:
    """The query's words that name something: mixed case or letters with digits ("HalOmi", "NLLB-200", "YOLOv8"),
    or all capitals of three letters or more ("COMET"), less the field's common acronyms."""
    out = set()
    for word in re.findall(r"[\w\-]+", query):
        bare = word.strip("-")
        if len(bare) < 3 or bare.lower() in COMMON_NAMES:
            continue
        mixed = any(c.isupper() for c in bare[1:]) and any(c.islower() for c in bare)
        digits = any(c.isdigit() for c in bare) and any(c.isalpha() for c in bare)
        if mixed or digits or (bare.isupper() and len(bare) >= 3):
            out.add(_normalise_title(bare))
    return out


def title_match(query: str, title: str | None) -> int:
    """3 if the title is the query, 2 if one contains the other (a short query, or a pasted title), 1 if the title
    carries a name the query uses, else 0."""
    q, t = _normalise_title(query), _normalise_title(title)
    if not q or not t:
        return 0
    if q == t:
        return 3
    # A title inside the query counts when it is most of the query (a pasted title), not a phrase of a question:
    # "Massively Multilingual Neural Machine Translation" is a paper and a subject.
    if (len(q.split()) <= CONTAINS_MAX_WORDS and f" {q} " in f" {t} ") or (
            len(t.split()) >= max(4, PASTED_SHARE * len(q.split())) and f" {t} " in f" {q} "):
        return 2
    qw, tw = [w for w in q.split() if w not in FILLER], [w for w in t.split() if w not in FILLER]
    if _shared_phrase(qw, tw) >= max(PHRASE_WORDS, len(qw) / 2):
        return 2   # "No Language Left Behind NLLB-200" -> "No Language Left Behind: Scaling …"
    words = set(t.split())
    found = names(query)
    return 1 if found and any(set(n.split()) <= words for n in found) else 0


def _shared_phrase(a: list[str], b: list[str]) -> int:
    """The length of the longest run of words ``a`` and ``b`` share."""
    best, prev = 0, [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, start=1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def relevant_local(papers: list[dict], query: str, floor: float = LOCAL_FLOOR) -> list[dict]:
    """The library hits that are about the query: close enough in meaning, or matched by title or keywords."""
    return [p for p in papers if (p.get("score") or 0) >= floor or p.get("match") in ("exact", "both", "keyword")
            or title_match(query, p.get("title")) > 0]


def merge_results(local: list[dict], live: list[dict], max_total: int = 20, keep_order: bool = False,
                  query: str | None = None) -> list[dict]:
    """Library and live papers, taken in turns, without duplicate titles.

    - A duplicate title (case- and punctuation-insensitive) is kept once, at its best place, as the library's
      copy: it carries Athena's id and summary.
    - Live papers keep the order given with ``keep_order`` (relevance, through ``interleave``), else most cited
      first.
    - With ``query``, titles that match it (``title_match``) lead, best match first.
    """
    if max_total <= 0:
        return []
    live = live if keep_order else sorted(live, key=lambda p: (p.get("citation_count") or 0), reverse=True)
    library = {_normalise_title(p.get("title")): p for p in reversed(local) if _normalise_title(p.get("title"))}

    seen: set[str] = set()
    merged: list[dict] = []
    for paper in interleave(live, local):
        key = _normalise_title(paper.get("title"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(library.get(key, paper))
    if query:
        merged.sort(key=lambda p: -title_match(query, p.get("title")))   # stable: relevance order within a level
    # Library hits by meaning alone: at most LIBRARY_SHARE of the list, unless nothing else is left.
    cap, kept, rest = max(1, round(max_total * LIBRARY_SHARE)), [], []
    for p in merged:
        weak = p.get("source") == "local" and p.get("match") == "meaning" and not (query and title_match(query, p.get(
            "title")))
        if weak and sum(1 for k in kept if k.get("_weak")) >= cap:
            rest.append(p)
            continue
        kept.append(p | {"_weak": True} if weak else p)
    out = [{k: v for k, v in p.items() if k != "_weak"} for p in kept + rest]
    return out[:max_total]
