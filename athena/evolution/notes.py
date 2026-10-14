"""
One-line notes for the reading path: why each paper matters, written by the chat model.

Notes are written in the API process after a reading path is served without
them (like Q&A, so they never wait behind a topic build on the evolution
queue) and stored per topic build: a rebuild makes them stale and the next
read writes them again. A Redis lock keeps two requests from writing the same
topic's notes at once; a failure is remembered for a few minutes so the page
stops waiting instead of retrying on every poll.
"""
from __future__ import annotations

from uuid import UUID

from loguru import logger

SYSTEM = "You write short, factual notes about research papers for newcomers to a field. Reply with JSON only."
SCHEMA = {"type": "object", "properties": {"abstract_matches": {"type": "boolean"},
                                           "why": {"type": "string", "maxLength": 360}},
          "required": ["abstract_matches", "why"], "additionalProperties": False}
MAX_WORDS = 48  # asked for 25; the model often runs longer, and a cut sentence reads worse
ABSTRACT_CHARS = 1500
LOCK_SECONDS = 300
FAILED_SECONDS = 300


def _lock_key(slug: str) -> str:
    return f"evo:notes:{slug}"


def _failed_key(slug: str) -> str:
    return f"evo:notes:failed:{slug}"


def claim(r, slug: str) -> bool:
    """Take the topic's writing lock; False when another request is already writing its notes."""
    return bool(r.set(_lock_key(slug), "1", nx=True, ex=LOCK_SECONDS))


def last_failure(r, slug: str) -> str | None:
    value = r.get(_failed_key(slug))
    return value.decode() if isinstance(value, bytes) else value


def prompt(topic_name: str, paper: dict) -> str:
    lines = [f"Research topic: {topic_name}",
             f"Paper: {paper['title']} ({paper['year'] or 'year unknown'})"]
    if paper.get("name") and paper["name"].lower() not in paper["title"].lower():
        lines.append(f"Usually called: {paper['name']}")
    if paper.get("abstract"):
        lines.append(f"Abstract: {paper['abstract'][:ABSTRACT_CHARS]}")
    if paper.get("builds_on"):
        lines.append("It cites these earlier papers on the same reading list: " + "; ".join(paper["builds_on"]))
    if paper.get("kind") == "survey":
        task = (f"In one sentence of at most 25 words, say what this survey covers and why a newcomer to "
                f"{topic_name} should read it first.")
    else:
        # Asking what it "changed" from earlier papers on the list made the model invent links (DETR
        # "replaced FPN and Mask R-CNN components"). Strict-link sentences are left out too: one of FPN's is an
        # experimental detail ("we include the anchor boxes outside the image"), which became its note.
        task = (f"In one sentence of at most 25 words, say what idea this paper introduced to {topic_name} and "
                "why it matters. Mention an earlier paper on the list only if the abstract says how this paper "
                "differs from it. Use only the information above.")
    if paper.get("abstract"):
        # OpenAlex sometimes attaches another work's abstract (DDPM's is about methylation imputation; DPR's is
        # a list of authors), and the model then wrote about the mismatch instead of a note. It now flags it,
        # and ``write_notes`` asks again without the abstract.
        check = ("First check that the abstract is about the paper in the title: set abstract_matches to false "
                 "if it describes other work or is not an abstract.")
    else:
        task = (f"In one sentence of at most 25 words, say what idea this paper introduced to {topic_name} and why "
                "it matters. Only the title is known: write from what is known about this paper, and leave why "
                "empty if you do not know it.")
        check = "Set abstract_matches to false."
    return ("\n".join(lines) + "\n\n" + task + " No author names, no praise words.\n" + check + "\n"
            + 'Return {"abstract_matches": true or false, "why": "<one sentence>"}.')


def clean(text: str | None) -> str:
    """The note, or "" when there is none to show (empty, or too long to be one sentence)."""
    text = " ".join(str(text or "").split()).strip().strip('"')
    return text if len(text.split()) <= MAX_WORDS else ""


def write_notes(slug: str, paper_ids: list[UUID], r) -> int:
    """Write the missing notes for ``paper_ids`` (in path order), then release the lock. Returns how many."""
    from athena.core import llm
    from athena.database import evolution as db
    from athena.database.db import SessionLocal

    written = 0
    try:
        with SessionLocal() as session:
            topic = db.get_topic(session, slug)
            if topic is None:
                return 0
            have = db.current_notes(session, topic, paper_ids)
            for paper in db.note_context(session, topic, paper_ids):
                if paper["paper_id"] in have:
                    continue
                answer, usage = llm.chat_json(prompt(topic.name, paper), SCHEMA, "paper_note", system=SYSTEM,
                                              max_tokens=160, feature="reading_notes")
                if answer is not None and paper.get("abstract") and answer.get("abstract_matches") is False:
                    answer, usage = llm.chat_json(prompt(topic.name, paper | {"abstract": None}), SCHEMA,
                                                  "paper_note", system=SYSTEM, max_tokens=160,
                                                  feature="reading_notes")
                if answer is None:
                    logger.warning(f"Reading path {slug}: the model's answer for {paper['title']!r} did not parse")
                    continue  # tried again on the next read
                text = clean(answer.get("why"))
                if not text:
                    logger.info(f"Reading path {slug}: no note for {paper['title']!r}: {answer}")
                # Stored even when empty, so a paper the model cannot describe is not asked about on every read.
                db.save_note(session, topic, paper["paper_id"], text, usage["model"])
                written += bool(text)
        r.delete(_failed_key(slug))
    except Exception as exc:  # the model server is down, or the database went away
        logger.warning(f"Reading path {slug}: notes not written: {exc}")
        r.set(_failed_key(slug), str(exc)[:300], ex=FAILED_SECONDS)
    finally:
        r.delete(_lock_key(slug))
    logger.info(f"Reading path {slug}: wrote {written} notes")
    return written
