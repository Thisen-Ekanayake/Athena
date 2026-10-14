"""
Exports of a map: papers as BibTeX, RIS or Markdown, and gap themes as CSV.

Pure functions over plain dicts, so the API and any later export (saved lists,
literature reviews) can share them. A paper dict has title, year, authors
(names), venue, doi, arxiv_id and url; ``why`` and ``named_method`` are used by
Markdown when present.

Saved lists add three optional keys: ``kind_hint`` "online" for a blog post (BibTeX
@misc with howpublished, note and urldate; RIS BLOG), its ``publisher`` (the source)
and ``accessed`` date, and ``note``: the reader's own note, exported as BibTeX
``annote`` and RIS ``N1`` lines.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Iterable

_LATEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                  "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
# Journals whose names start like a conference's proceedings.
_JOURNAL = re.compile(r"^proceedings of the (ieee|national academy|royal society|vldb)", re.IGNORECASE)
_CONFERENCE = re.compile(r"conference|proceedings|workshop|symposium|\b(cvpr|iccv|eccv|neurips|nips|icml|iclr|acl|"
                         r"emnlp|naacl|aaai|ijcai|kdd|sigir)\b", re.IGNORECASE)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in text)


def _surname(author: str) -> str:
    parts = author.replace(",", " ").split()
    return parts[-1] if parts else ""


def _kind(paper: dict) -> str:
    if paper.get("kind_hint") == "online":
        return "online"
    venue = paper.get("venue") or ""
    if not venue or "arxiv" in venue.lower():
        return "misc"
    return "inproceedings" if _CONFERENCE.search(venue) and not _JOURNAL.search(venue) else "article"


def cite_keys(papers: list[dict]) -> list[str]:
    """``ren2015faster``-style keys: first author's surname (a blog post without one: its source's first word),
    year, first long title word; unique in the list."""
    keys, seen = [], {}
    for p in papers:
        authors = p.get("authors") or []
        name = _surname(authors[0]) if authors else ((p.get("publisher") or "anon").split() or ["anon"])[0]
        surname = re.sub(r"[^a-z]", "", _ascii(name).lower()) or "anon"
        words = [w for w in re.findall(r"[a-z]+", _ascii(p.get("title") or "").lower()) if len(w) > 3]
        base = f"{surname}{p.get('year') or ''}{words[0] if words else ''}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        keys.append(base if n == 0 else f"{base}{chr(ord('a') + n - 1)}")
    return keys


def _latex_note(text: str) -> str:
    """A multi-paragraph note as one BibTeX value: escaped, paragraphs joined by \\par."""
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text.strip())]
    return " \\par ".join(latex_escape(part) for part in paragraphs if part)


def bibtex(papers: list[dict]) -> str:
    entries = []
    for key, p in zip(cite_keys(papers), papers):
        kind = _kind(p)
        fields = [("title", "{" + latex_escape(p["title"]) + "}"),  # double braces keep the title's capitals
                  ("author", " and ".join(latex_escape(a) for a in p.get("authors") or [] if a))]
        if p.get("year"):
            fields.append(("year", str(p["year"])))
        if kind == "article":
            fields.append(("journal", latex_escape(p["venue"])))
        elif kind == "inproceedings":
            fields.append(("booktitle", latex_escape(p["venue"])))
        elif kind == "online":
            if p.get("url"):
                fields.append(("howpublished", "\\url{" + p["url"] + "}"))
            if p.get("publisher"):
                fields.append(("note", latex_escape(p["publisher"])))
            if p.get("accessed"):
                fields.append(("urldate", str(p["accessed"])))
        if p.get("doi"):
            fields.append(("doi", p["doi"]))
        if p.get("arxiv_id"):
            fields += [("eprint", p["arxiv_id"]), ("archivePrefix", "arXiv")]
        if p.get("url"):
            fields.append(("url", p["url"]))
        if p.get("note"):
            fields.append(("annote", _latex_note(p["note"])))
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
        # A blog post is @misc: biblatex's @online is not understood by plain BibTeX styles.
        entries.append(f"@{'misc' if kind == 'online' else kind}{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"


def ris(papers: list[dict]) -> str:
    types = {"article": "JOUR", "inproceedings": "CONF", "misc": "GEN", "online": "BLOG"}
    records = []
    for p in papers:
        kind = _kind(p)
        lines = [f"TY  - {types[kind]}", f"TI  - {p['title']}"]
        lines += [f"AU  - {a}" for a in p.get("authors") or [] if a]
        if p.get("year"):
            lines.append(f"PY  - {p['year']}")
        if p.get("venue") and kind in ("article", "inproceedings"):
            lines.append(f"{'JO' if kind == 'article' else 'T2'}  - {p['venue']}")
        if kind == "online" and p.get("publisher"):
            lines.append(f"PB  - {p['publisher']}")
        if kind == "online" and p.get("accessed"):
            lines.append(f"Y2  - {p['accessed']}")
        if p.get("doi"):
            lines.append(f"DO  - {p['doi']}")
        if p.get("url"):
            lines.append(f"UR  - {p['url']}")
        if p.get("arxiv_id"):
            lines.append(f"N1  - arXiv:{p['arxiv_id']}")
        for paragraph in re.split(r"\n\s*\n", (p.get("note") or "").strip()):
            if paragraph.strip():
                lines.append(f"N1  - {' '.join(paragraph.split())}")
        lines.append("ER  - ")
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


def _md_line(p: dict) -> str:
    authors = p.get("authors") or []
    who = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    name = f" ({p['named_method']})" if p.get("named_method") and p["named_method"] not in p["title"] else ""
    parts = [f"**[{p['title']}]({p['url']})**{name}" if p.get("url") else f"**{p['title']}**{name}",
             f"({p['year']})" if p.get("year") else ""]
    tail = ". ".join(x.rstrip(".") for x in (who, f"*{p['venue']}*" if p.get("venue") else "") if x)
    return " ".join(x for x in parts if x) + (f". {tail}." if tail else "")


def markdown_path(topic_name: str, survey: dict | None, steps: list[dict], built: str | None) -> str:
    out = [f"# Reading path: {topic_name}", "",
           f"{len(steps) + bool(survey)} papers: a survey first, then the milestones in the order they appeared."
           + (f" From Athena's map built {built}." if built else ""), ""]
    for i, p in enumerate(([survey] if survey else []) + steps, start=1):
        out.append(f"{i}. {_md_line(p)}" + (" *(start here)*" if survey is not None and p is survey else ""))
        if p.get("why"):
            out.append(f"   {p['why']}")
    return "\n".join(out) + "\n"


def markdown_milestones(topic_name: str, papers: list[dict], built: str | None) -> str:
    out = [f"# Milestones: {topic_name}", ""]
    if built:
        out += [f"From Athena's map built {built}.", ""]
    year = object()
    for p in sorted(papers, key=lambda p: (p.get("year") or 0, p["title"])):
        if p.get("year") != year:
            year = p.get("year")
            out += ["", f"## {year or 'Year unknown'}", ""]
        out.append(f"- {_md_line(p)}")
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


GAP_COLUMNS = ["theme", "status", "first_year", "last_year", "theme_size", "statement", "origin", "section",
               "paper", "paper_year", "stated_by", "stated_by_year"]


def gaps_csv(rows: Iterable[dict]) -> str:
    """One row per gap statement, with its theme. ``rows`` hold the GAP_COLUMNS keys."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=GAP_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if row.get(k) is None else row[k] for k in GAP_COLUMNS})
    return buf.getvalue()
