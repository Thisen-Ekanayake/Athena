"""
People view: the key authors and labs of each era, and who introduced each milestone (ROADMAP E8).

Authors of an era are ranked by how many of its milestones they wrote, then by
the sum of the squared milestone scores of their on-topic method papers from
those years. Weight alone put prolific authors of follow-ups first (in PEFT's
2021, an author of eight minor papers above the authors of LoRA and prompt
tuning); squaring keeps one strong paper ahead of several weak ones among the
rest. Labs are ranked the same way, each counted once per paper. Authors are
told apart by OpenAlex author ID; papers without authorships fall back to the
name, normalised.

Pure functions; ``athena.database.evolution.topic_people`` feeds them.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from athena.evolution.eras import find_era

TOP_AUTHORS = 8
TOP_LABS = 6


@dataclass
class PeoplePaper:
    id: str
    title: str
    year: int | None
    milestone_score: float
    is_milestone: bool
    named_method: str | None = None
    authorships: list[dict] = field(default_factory=list)  # [{id, name, institutions: [{id, name, country}]}]
    authors: list[str] = field(default_factory=list)       # names, when there are no authorships

    @property
    def people(self) -> list[dict]:
        if self.authorships:
            return self.authorships
        return [{"id": None, "name": n, "institutions": []} for n in self.authors if n]

    @property
    def weight(self) -> float:
        return self.milestone_score ** 2


def _normal(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(plain.replace(".", " ").replace("-", " ").split())


def author_key(author: dict) -> str:
    return author.get("id") or f"name:{_normal(author.get('name') or '')}"


def lab_key(institution: dict) -> str:
    return institution.get("id") or f"name:{_normal(institution.get('name') or '')}"


def _mini(p: PeoplePaper) -> dict:
    return {"id": p.id, "title": p.title, "year": p.year, "named_method": p.named_method,
            "is_milestone": p.is_milestone}


def _rank(papers: list[PeoplePaper], keys_of, label_of, top: int) -> list[dict]:
    weight: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    milestones: dict[str, int] = defaultdict(int)
    best: dict[str, PeoplePaper] = {}
    info: dict[str, dict] = {}
    for p in papers:
        for key, item in keys_of(p).items():
            weight[key] += p.weight
            count[key] += 1
            milestones[key] += p.is_milestone
            info.setdefault(key, item)
            if key not in best or p.milestone_score > best[key].milestone_score:
                best[key] = p
    ranked = sorted(weight, key=lambda k: (-milestones[k], -weight[k], label_of(info[k])))[:top]
    return [{**info[k], "papers": count[k], "milestones": milestones[k], "weight": round(weight[k], 3),
             "best_paper": _mini(best[k])} for k in ranked]


def _authors_of(p: PeoplePaper) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in p.people:
        if a.get("name"):
            out.setdefault(author_key(a), {"id": a.get("id"), "name": a["name"]})
    return out


def _labs_of(p: PeoplePaper) -> dict[str, dict]:
    """Each institution once per paper, however many of its authors are there."""
    out: dict[str, dict] = {}
    for a in p.people:
        for inst in a.get("institutions") or []:
            if inst.get("name"):
                out.setdefault(lab_key(inst), {"id": inst.get("id"), "name": inst["name"],
                                               "country": inst.get("country")})
    return out


def people_by_era(papers: list[PeoplePaper], eras: list[tuple[int, int]],
                  top_authors: int = TOP_AUTHORS, top_labs: int = TOP_LABS) -> list[dict]:
    """Key authors and labs of each era, oldest era first. ``papers``: the topic's on-topic method papers."""
    by_era: dict[tuple[int, int], list[PeoplePaper]] = defaultdict(list)
    for p in papers:
        era = find_era(p.year, eras)
        if era is not None:
            by_era[era].append(p)
    return [{"start": start, "end": end, "papers": len(by_era[(start, end)]),
             "authors": _rank(by_era[(start, end)], _authors_of, lambda a: a["name"], top_authors),
             "labs": _rank(by_era[(start, end)], _labs_of, lambda i: i["name"], top_labs)}
            for start, end in eras if by_era.get((start, end))]


def milestone_people(papers: list[PeoplePaper]) -> list[dict]:
    """Who introduced each milestone, oldest first."""
    return [_mini(p) | {"authors": [{"id": a.get("id"), "name": a["name"],
                                     "institutions": [i["name"] for i in a.get("institutions") or []]}
                                    for a in p.people if a.get("name")]}
            for p in sorted((p for p in papers if p.is_milestone), key=lambda p: (p.year or 0, p.title))]


def key_people(papers: list[PeoplePaper], top: int = TOP_AUTHORS) -> dict:
    """The topic's key authors and labs over all its years."""
    return {"authors": _rank(papers, _authors_of, lambda a: a["name"], top),
            "labs": _rank(papers, _labs_of, lambda i: i["name"], top)}
