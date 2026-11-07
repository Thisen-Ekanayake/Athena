"""
The ACL Anthology's metadata: fetched from its GitHub repository, read from its XML, kept in ``conf_*`` tables.

The repository holds one XML file per event (``data/xml/2024.acl.xml``, ``P18.xml``). Its Python library clones it
with git, which Athena's images do not have, so the importer streams the repository's tarball instead (about 65 MB)
and keeps only ``data/xml``; the commit it came from is kept beside it, so an unchanged repository is not fetched
again.
"""
from __future__ import annotations

import io
import re
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger
from lxml import etree
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from athena.conferences import venues as V
from athena.core.config_store import get_setting
from athena.core.models import ConfPaper, ConfVolume, ConfVolumeVenue

REPO = "acl-org/acl-anthology"
BRANCH = "master"
TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{BRANCH}"
COMMIT_API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
SITE = "https://aclanthology.org"
# Entries that are not papers, mostly from the Computational Linguistics journal: reviews, indexes, notices.
NOT_PAPERS = re.compile(
    r"^\s*(book reviews?|briefly noted|errat(um|a)|corrigend|obituar|in memoriam|publications received"
    r"|letters? to the editor|front ?matter|back ?matter|abstracts of current literature|the finite string"
    r"|current bibliography|announcements?|calls? for papers|acl lifetime achievement|presidential address"
    r"|reviewers|author index|table of contents|editorial)\b", re.I)


def data_dir() -> Path:
    return Path(get_setting("ANTHOLOGY_DIR", str(Path.home() / ".athena" / "anthology")))


# ── fetching ──────────────────────────────────────────────────────────


def latest_commit(http: httpx.Client) -> str | None:
    try:
        resp = http.get(COMMIT_API, headers={"Accept": "application/vnd.github.sha"})
        resp.raise_for_status()
        return resp.text.strip() or None
    except httpx.HTTPError as exc:
        logger.warning(f"Could not ask GitHub for the Anthology's latest commit: {exc}")
        return None


def fetch(force: bool = False, http: httpx.Client | None = None) -> tuple[Path, bool]:
    """The directory of the Anthology's XML files, and whether it changed. Downloads only when the repository has a
    newer commit than the copy here (or ``force``)."""
    root = data_dir()
    xml_dir, marker = root / "xml", root / "COMMIT"
    own = http is None
    http = http or httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True)
    try:
        commit = latest_commit(http)
        have = marker.read_text().strip() if marker.exists() else None
        if not force and xml_dir.is_dir() and any(xml_dir.iterdir()) and (commit is None or commit == have):
            return xml_dir, False
        logger.info(f"Downloading the ACL Anthology's metadata ({commit or 'latest'})")
        fresh = root / "xml.new"
        shutil.rmtree(fresh, ignore_errors=True)
        fresh.mkdir(parents=True)
        count = 0
        with http.stream("GET", TARBALL) as resp:
            resp.raise_for_status()
            with tarfile.open(fileobj=_Stream(resp.iter_bytes()), mode="r|gz") as tar:
                for member in tar:
                    parts = member.name.split("/")
                    if member.isfile() and len(parts) == 4 and parts[1:3] == ["data", "xml"] \
                            and parts[3].endswith(".xml"):
                        (fresh / parts[3]).write_bytes(tar.extractfile(member).read())
                        count += 1
        if not count:
            raise RuntimeError("The Anthology's tarball held no data/xml files")
        shutil.rmtree(xml_dir, ignore_errors=True)
        fresh.rename(xml_dir)
        if commit:
            marker.write_text(commit)
        logger.info(f"ACL Anthology: {count} XML files")
        return xml_dir, True
    finally:
        if own:
            http.close()


class _Stream(io.RawIOBase):
    """Byte chunks as a file, for tarfile's streaming mode."""

    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self._buf = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while not self._buf:
            try:
                self._buf = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buf))
        b[:n], self._buf = self._buf[:n], self._buf[n:]
        return n


# ── reading the XML ───────────────────────────────────────────────────


@dataclass
class Paper:
    id: str
    title: str
    abstract: str | None
    authors: list[str]
    doi: str | None
    awards: list[str]


@dataclass
class Volume:
    id: str
    year: int
    kind: str
    title: str
    venues: list[str]
    papers: list[Paper] = field(default_factory=list)


def _text(el) -> str | None:
    if el is None:
        return None
    text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
    return text or None


def _name(author) -> str:
    return " ".join(p for p in (_text(author.find("first")), _text(author.find("last"))) if p)


def paper_id(collection: str, volume: str, paper: str) -> str:
    """The Anthology id: 2024.acl-long.1 for new collections; for old ones volume and paper in four digits, P18-1031
    (two and two for workshops, COLING 1969 and EMNLP 2019's workshop volumes, as the Anthology's library does)."""
    if re.match(r"^\d{4}\.", collection):
        return f"{collection}-{volume}.{paper}"
    if collection[0] == "W" or collection == "C69" or (collection == "D19" and int(volume) >= 5):
        return f"{collection}-{int(volume):02d}{int(paper):02d}"
    return f"{collection}-{int(volume):01d}{int(paper):03d}"


def read_file(path: Path) -> list[Volume]:
    """The volumes of one XML file that are proceedings of a followed venue, with their papers."""
    root = etree.parse(str(path)).getroot()
    collection = root.get("id") or path.stem
    out = []
    for vol in root.iter("volume"):
        meta = vol.find("meta")
        if meta is None:
            continue
        vid = f"{collection}-{vol.get('id')}"
        tags = [t.text.strip() for t in meta.findall("venue") if t.text]
        venues = V.volume_venues(vid, tags)
        title = _text(meta.find("booktitle")) or vid
        kind = V.volume_kind(vid, title, tags, venues)
        year = meta.findtext("year")
        if kind is None or not (year and year.strip().isdigit()):
            continue
        volume = Volume(id=vid, year=int(year), kind=kind, title=title, venues=venues)
        for p in vol.findall("paper"):
            if p.get("id") in (None, "0") or p.find("removed") is not None or p.find("retracted") is not None:
                continue
            ptitle = _text(p.find("title"))
            if not ptitle or NOT_PAPERS.search(ptitle):
                continue
            awards = [a.get("name") or _text(a) for a in p.findall("award")]
            volume.papers.append(Paper(
                id=paper_id(collection, vol.get("id"), p.get("id")), title=ptitle, abstract=_text(p.find("abstract")),
                authors=[n for n in (_name(a) for a in p.findall("author")) if n],
                doi=(p.findtext("doi") or "").strip() or None, awards=[a for a in awards if a]))
        if volume.papers:
            out.append(volume)
    return out


def read_all(xml_dir: Path) -> list[Volume]:
    volumes = []
    for path in sorted(xml_dir.glob("*.xml")):
        try:
            volumes += read_file(path)
        except etree.XMLSyntaxError as exc:
            logger.warning(f"Skipping {path.name}: {exc}")
    return volumes


def page_url(pid: str) -> str:
    return f"{SITE}/{pid}/"


def pdf_url(pid: str) -> str:
    return f"{SITE}/{pid}.pdf"


# ── storing ───────────────────────────────────────────────────────────


def store(session: Session, volumes: list[Volume]) -> dict:
    """Bring the tables in line with ``volumes``: new and changed papers, volumes and venues; papers and volumes the
    Anthology no longer lists are dropped. A changed title or abstract clears the paper's embedding and topic, so
    they are made again. ``removed`` lists the ids of dropped papers, whose vectors go too."""
    now = datetime.now(timezone.utc)
    stats = {"volumes": len(volumes), "papers": 0, "new": 0, "changed": 0, "removed": []}
    known_volumes = {v.id: v for v in session.execute(select(ConfVolume)).scalars()}
    venue_rows = {(r.volume_id, r.venue) for r in session.execute(select(ConfVolumeVenue)).scalars()}
    keep_volumes = set()
    for vol in volumes:
        keep_volumes.add(vol.id)
        row = known_volumes.get(vol.id)
        if row is None:
            row = ConfVolume(id=vol.id)
            session.add(row)
        row.year, row.kind, row.title, row.paper_count, row.updated_at = (
            vol.year, vol.kind, vol.title, len(vol.papers), now)
        want = {(vol.id, v) for v in vol.venues}
        have = {r for r in venue_rows if r[0] == vol.id}
        for _, venue in want - have:
            session.add(ConfVolumeVenue(volume_id=vol.id, venue=venue))
        for _, venue in have - want:
            session.execute(delete(ConfVolumeVenue).where(ConfVolumeVenue.volume_id == vol.id,
                                                          ConfVolumeVenue.venue == venue))
    session.flush()

    for vol in volumes:
        existing = {p.id: p for p in session.execute(
            select(ConfPaper).where(ConfPaper.volume_id == vol.id)).scalars()}
        for p in vol.papers:
            stats["papers"] += 1
            row = existing.pop(p.id, None)
            rank = V.award_rank(p.awards)
            if row is None:
                session.add(ConfPaper(id=p.id, volume_id=vol.id, year=vol.year, title=p.title, abstract=p.abstract,
                                      abstract_from="anthology" if p.abstract else None, authors=p.authors, doi=p.doi,
                                      awards=p.awards, award_rank=rank, updated_at=now))
                stats["new"] += 1
                continue
            # An abstract found elsewhere (athena.conferences.citations) stays until the Anthology has its own.
            abstract, source = (p.abstract, "anthology") if p.abstract else (row.abstract, row.abstract_from)
            if row.abstract_from == "anthology" and not p.abstract:
                abstract, source = None, None
            if (row.title, row.abstract) != (p.title, abstract):
                row.embedded_at = row.embed_model = row.topic_id = row.topic_score = None
            fields = {"year": vol.year, "title": p.title, "abstract": abstract, "abstract_from": source,
                      "authors": p.authors, "doi": p.doi, "awards": p.awards, "award_rank": rank}
            if any(getattr(row, k) != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(row, k, v)
                row.updated_at = now
                stats["changed"] += 1
        for gone in existing.values():
            session.delete(gone)
            stats["removed"].append(gone.id)
    for vid, row in known_volumes.items():
        if vid not in keep_volumes:
            stats["removed"] += list(session.execute(select(ConfPaper.id).where(ConfPaper.volume_id == vid)).scalars())
            session.delete(row)
    session.commit()
    return stats
