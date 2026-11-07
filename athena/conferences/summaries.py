"""
A few sentences on what each venue's edition was about, written by the chat model from the edition's numbers (topic
shares and their change, rising and falling terms, award winners) and kept until those numbers change.

Backlog work: newest editions first, the whole family's year before its venues, only once an edition's papers are
sorted into topics. Takes turns on the GPU like the rest (``lane.yield_to_chat``).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from athena.conferences import venues as V
from athena.core import llm
from athena.core.models import ConfSummary
from athena.database import conferences as db
from athena.database.db import SessionLocal
from athena.model_server import lane

FEATURE = "conf_summary"
KINDS = list(V.KINDS)
SORTED_ENOUGH = 0.95   # of an edition's papers sorted before it is summarised
SYSTEM = ("You write short, factual overviews of natural language processing conference editions for researchers. "
          "Use only the numbers you are given. Plain prose, no lists, no headings, no preamble.")
PROMPT = """The numbers of {venue} {year}{since}:

{numbers}

In three or four sentences, say what this edition was about and how it moved: name its biggest topics, the topics \
that grew or shrank most since the previous edition (in percentage points), what the rising terms say is new, and \
what the award-winning papers were about. Say "papers" for the edition's papers. Do not list every number."""
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
          "additionalProperties": False}


def numbers_hash(numbers: dict) -> str:
    stable = {k: v for k, v in numbers.items() if k != "sorted"}
    return hashlib.sha1(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def due(session: Session) -> list[tuple[str, int]]:
    """Editions whose summary is missing or was written from other numbers, newest first."""
    out = []
    for venue in [V.ALL, *V.VENUES]:
        for year, papers in db.years(session, venue, KINDS).items():
            if papers < 20:
                continue
            out.append((venue, year))
    out.sort(key=lambda e: (-e[1], e[0] != V.ALL))
    stale = []
    for venue, year in out:
        done = db.progress(session, venue, year, KINDS)
        if done["sorted"] < SORTED_ENOUGH * done["papers"]:
            continue
        have = session.get(ConfSummary, (venue, year))
        if have is None or have.stats_hash != numbers_hash(db.edition_numbers(session, venue, year, KINDS)):
            stale.append((venue, year))
    return stale


def write(session: Session, venue: str, year: int) -> str | None:
    numbers = db.edition_numbers(session, venue, year, KINDS)
    if not numbers:
        return None
    model = llm.chat_model()
    lane.yield_to_chat(who=FEATURE, model=model)
    since = f" (changes since {numbers['previous_year']})" if numbers.get("previous_year") else ""
    shown = {k: v for k, v in numbers.items() if k not in ("venue", "year", "sorted")}
    answer, _ = llm.chat_json(PROMPT.format(venue=numbers["venue"], year=year, since=since,
                                            numbers=json.dumps(shown, indent=1)),
                              SCHEMA, "edition_summary", system=SYSTEM, max_tokens=450, feature=FEATURE)
    text = " ".join(((answer or {}).get("summary") or "").split())
    if not text:
        return None
    row = session.get(ConfSummary, (venue, year)) or ConfSummary(venue=venue, year=year)
    row.text, row.stats_hash, row.model = text, numbers_hash(numbers), model
    row.written_at = datetime.now(timezone.utc)
    session.merge(row)
    session.commit()
    return text


def run(deadline: float | None = None) -> dict:
    written = 0
    with SessionLocal() as session:
        for venue, year in due(session):
            if deadline is not None and time.monotonic() > deadline:
                return {"written": written, "more": True}
            try:
                if write(session, venue, year):
                    written += 1
            except lane.Paused:
                raise
            except Exception as exc:
                logger.warning(f"Conference summary for {venue} {year} failed: {exc}")
                session.rollback()
    return {"written": written, "more": False}
