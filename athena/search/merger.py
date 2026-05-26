"""Merge local and live search results into a single deduplicated list."""
from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalise_title(title: str | None) -> str:
    if not title:
        return ""
    lowered = title.lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()


def merge_results(local: list[dict], live: list[dict], max_total: int = 20) -> list[dict]:
    """Merge local + live papers.

    - Local results come first.
    - Duplicate titles (case- and punctuation-insensitive) are removed;
      the local copy wins because it carries richer metadata.
    - Remaining live slots are filled in descending citation_count order.
    """
    if max_total <= 0:
        return []

    seen: set[str] = set()
    merged: list[dict] = []

    for paper in local:
        title_key = _normalise_title(paper.get("title"))
        if title_key and title_key in seen:
            continue
        if title_key:
            seen.add(title_key)
        merged.append(paper)
        if len(merged) >= max_total:
            return merged

    remaining = max_total - len(merged)
    if remaining <= 0:
        return merged

    sorted_live = sorted(
        live,
        key=lambda p: (p.get("citation_count") or 0),
        reverse=True,
    )
    for paper in sorted_live:
        title_key = _normalise_title(paper.get("title"))
        if title_key and title_key in seen:
            continue
        if title_key:
            seen.add(title_key)
        merged.append(paper)
        if len(merged) >= max_total:
            break

    return merged
