"""
The venues Athena follows, and which Anthology volumes count as their proceedings.

Every volume in the Anthology's XML names its venues (``<venue>acl</venue>``); Findings volumes name only
``findings``, so their venue comes from the volume id (``2024.findings-acl``). Only main proceedings (long and short
papers, posters), Findings and the two journals count: demos, student workshops, tutorials, industry tracks and
workshops are left out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    slug: str
    name: str
    full_name: str
    journal: bool = False


VENUES: dict[str, Venue] = {v.slug: v for v in (
    Venue("acl", "ACL", "Annual Meeting of the Association for Computational Linguistics"),
    Venue("emnlp", "EMNLP", "Conference on Empirical Methods in Natural Language Processing"),
    Venue("naacl", "NAACL", "Nations of the Americas Chapter of the ACL"),
    Venue("eacl", "EACL", "European Chapter of the ACL"),
    Venue("aacl", "AACL", "Asia-Pacific Chapter of the ACL (with IJCNLP)"),
    Venue("coling", "COLING", "International Conference on Computational Linguistics"),
    Venue("tacl", "TACL", "Transactions of the Association for Computational Linguistics", journal=True),
    Venue("cl", "CL", "Computational Linguistics", journal=True),
)}
# The whole family at once, in every view that takes a venue.
ALL = "all"
FAMILY_NAME = "ACL family"
KINDS = ("main", "findings", "journal")

# Findings of IJCNLP-AACL are AACL's.
FINDINGS_OF = {"ijcnlp": "aacl"}
# Volumes that are not the main programme, by title or id.
_SIDE = re.compile(r"demo|student|\bsrw\b|tutorial|industry|doctoral|consortium|interactive|invited|keynote|panel"
                   r"|workshop|shared task", re.I)


def volume_venues(volume_id: str, tags: list[str]) -> list[str]:
    """The followed venues a volume counts for, from its ``<venue>`` tags and, for Findings, its id."""
    found = [t for t in tags if t in VENUES]
    if "findings" in tags or "findings-" in volume_id:
        m = re.search(r"findings-([a-z]+)", volume_id)
        if m:
            parent = FINDINGS_OF.get(m.group(1), m.group(1))
            if parent in VENUES and parent not in found:
                found.append(parent)
    return found


def volume_kind(volume_id: str, title: str, tags: list[str], venues: list[str]) -> str | None:
    """main, findings or journal; None for a volume that is not proceedings Athena keeps."""
    if not venues:
        return None
    if "findings" in tags or "findings-" in volume_id:
        return "findings"
    if all(VENUES[v].journal for v in venues):
        return "journal"
    collection = volume_id.split("-")[0]
    if re.fullmatch(r"W\d\d", collection):  # the old workshop collections
        return None
    if _SIDE.search(title) or _SIDE.search(volume_id.split("-", 1)[-1]):
        return None
    if "ws" in tags:
        return None
    return "main"


_TOP = re.compile(r"best (long |short |overall |student )?paper|test.of.time", re.I)
_SECOND = re.compile(r"outstanding|best", re.I)


def award_rank(awards: list[str]) -> int | None:
    """0 for a best paper or a test-of-time award, 1 for an outstanding or other "best" paper (resource, theme,
    social impact), 2 for the rest (SAC awards, honourable mentions); None without one. A paper's best award counts."""
    ranks = [0 if _TOP.search(a) else 1 if _SECOND.search(a) else 2
             for a in awards if not re.search(r"honou?rable|runner", a, re.I)]
    if not awards:
        return None
    return min(ranks) if ranks else 2


def label(venue: str) -> str:
    return FAMILY_NAME if venue == ALL else VENUES[venue].name
