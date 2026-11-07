"""
Rising and falling terms: the phrases of titles and abstracts whose share of a venue's papers changed most since its
previous edition.

Phrases are runs of one to three words without a stopword at either end, counted once per paper. The change is the
log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi and Quinn 2008, "Fightin' Words"), with the
whole family's counts as the prior, so rare phrases do not jump to the top on a handful of papers. A shorter phrase
that is almost always part of a longer one ("language" in "large language models") is left out. Old papers have
only titles, so their editions' terms are thinner. No model is needed.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from athena.conferences import venues as V
from athena.core.models import ConfPaper, ConfTerm, ConfVolumeVenue

KEEP_RISING = 25
KEEP_FALLING = 15
MIN_PAPERS = 5          # a phrase must be in this many papers of the edition (rising) or the previous one (falling)
MIN_EDITION = 40        # editions smaller than this get no terms
PRIOR_SCALE = 0.01      # how strongly the family's counts pull small counts toward no change
# Two editions are compared on titles and abstracts only when both have this share of abstracts, else on titles:
# an edition that gained abstracts would otherwise "rise" in every word abstracts use.
ABSTRACTS_SHARE = 0.8

# Never at either end of a phrase.
FUNCTION = set("""a about above across after again against all almost also although always am among an and another any
are around as at be because been before being below between both but by can cannot could did do does doing done
down during each either enough especially etc even ever every few for from further had has have having here how
however i if in into is it its itself just least less like many may might more most much must my neither no nor not
now of off often on once one only or other our out over own per perhaps rather same several she should since so
some such than that the their them then there these they this those though through thus to too toward towards
under until up upon us use used uses using very via was we well were what when where whether which while who whom
whose why will with within without would yet you your e.g i.e et al""".split())
# The vocabulary of every paper: fine inside a phrase ("large language models"), never a term alone.
GENERIC = set("""paper papers propose proposed proposes present presents show shows shown study studies work
approach approaches method methods task tasks model models based new novel results result performance experiments
experimental demonstrate achieve achieves state art first two three different various existing significantly
significant improve improves improved improvement large small
data also""".split())
# How papers are written rather than what they are about: these move with fashion in prose, not in research.
FILLER = set("""additionally abilities ability across addition address addresses addressing advance advances
advancements assess available called certain com diverse employing furthermore github higher http https thereby
analysis analyze analyzing aspects baseline baselines better beyond broad capabilities capability capture captures
case challenge challenges challenging code common complex comprehensive consistently consider considering contrast
crucial current demonstrates demonstrating designed despite develop developed effective effectively effectiveness
efficacy efficient efficiently empirical enable enables enhance enhanced enhances enhancing ensure especially
evaluate evaluated evaluating evidence explicit explicitly explore explores exploring extensive face finally findings
focus framework frameworks further gains general generalization generally given high highly human humans identify
impact importance important improving include including information insights introduce introduces introducing issue
issues key known lack language languages leading leads leverage leverages leveraging limited limitations lower main
make makes making manner multiple need needs notably novel number obtain offer offers often outperform outperforms
overall paradigm particular particularly perform performs potential practical present previous prior problem
problems process propose provide provides providing quality range real recent recently reduce reduces reliable
remains report research reveal reveals robust shed significant simple specific specifically strategies strategy
strong stronger struggle substantial substantially success successfully suggest superior system systems techniques terms
therefore time tool towards understanding unified use useful valuable well-known wide widely world""".split())
EDGE = FUNCTION | FILLER
ALONE = FUNCTION | GENERIC | FILLER
_WORD = re.compile(r"[a-z][a-z0-9\-]*[a-z0-9]|[a-z]")
_BREAK = re.compile(r"[.,;:!?()\[\]{}\"“”]|\s-\s|\s–\s")


def phrases(text: str) -> set[str]:
    """The phrases of one paper; none crosses punctuation, so "(LLMs)" does not join the words around it."""
    out = set()
    for part in _BREAK.split(text.lower()):
        words = _WORD.findall(part)
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if n == 1 and (gram[0] in ALONE or len(gram[0]) < 3):
                    continue
                if n > 1 and (gram[0] in EDGE or gram[-1] in EDGE):
                    continue
                out.add(" ".join(gram))
    return out


def _counts(texts: list[str]) -> Counter:
    c: Counter = Counter()
    for t in texts:
        c.update(phrases(t))
    return c


def log_odds(now: Counter, n_now: int, before: Counter, n_before: int, prior: Counter, n_prior: int,
             ) -> dict[str, float]:
    """z-scores of the change in each phrase's use from ``before`` to ``now`` (papers using it out of n)."""
    a0 = PRIOR_SCALE * n_now
    out = {}
    for term in set(now) | set(before):
        alpha = a0 * (prior.get(term, 0) + 1) / (n_prior + 1)
        y1, y2 = now.get(term, 0), before.get(term, 0)
        l1 = math.log((y1 + alpha) / (n_now + a0 - y1 - alpha))
        l2 = math.log((y2 + alpha) / (n_before + a0 - y2 - alpha))
        var = 1 / (y1 + alpha) + 1 / (y2 + alpha)
        out[term] = (l1 - l2) / math.sqrt(var)
    return out


def _subsumed(term: str, chosen: list[str], counts: Counter) -> bool:
    """Whether a longer chosen phrase holds ``term`` in most of its papers."""
    return any(term != c and f" {term} " in f" {c} " and counts[c] >= 0.75 * counts[term] for c in chosen)


def pick(scores: dict[str, float], counts: Counter, rising: bool, keep: int) -> list[str]:
    ranked = sorted((t for t in scores if counts.get(t, 0) >= MIN_PAPERS and (scores[t] > 0) == rising),
                    key=lambda t: -scores[t] if rising else scores[t])
    longest_first = sorted(ranked[:keep * 4], key=lambda t: -len(t.split()))
    chosen: list[str] = []
    for t in longest_first:
        if not _subsumed(t, chosen, counts):
            chosen.append(t)
    return [t for t in ranked if t in set(chosen)][:keep]


Edition = list[tuple[str, str | None]]  # (title, abstract) per paper


def _papers(session: Session, venue: str) -> dict[int, Edition]:
    q = select(ConfPaper.year, ConfPaper.title, ConfPaper.abstract)
    if venue != V.ALL:
        q = q.join(ConfVolumeVenue, ConfVolumeVenue.volume_id == ConfPaper.volume_id).where(
            ConfVolumeVenue.venue == venue)
    by_year: dict[int, Edition] = {}
    for year, title, abstract in session.execute(q):
        by_year.setdefault(year, []).append((title, abstract))
    return by_year


def _with_abstracts(edition: Edition) -> bool:
    return sum(1 for _, a in edition if a) >= ABSTRACTS_SHARE * len(edition)


def texts(edition: Edition, abstracts: bool) -> list[str]:
    return [f"{t}. {a or ''}" if abstracts else t for t, a in edition]


def compute(session: Session, venues: list[str] | None = None) -> int:
    """Rising and falling terms of every edition of ``venues`` (all, and the family per year, by default)."""
    family = _papers(session, V.ALL)
    prior: Counter = Counter()
    n_prior = 0
    for edition in family.values():
        prior.update(_counts(texts(edition, True)))
        n_prior += len(edition)
    written = 0
    for venue in venues or [V.ALL, *V.VENUES]:
        by_year = family if venue == V.ALL else _papers(session, venue)
        years = sorted(by_year)
        session.execute(delete(ConfTerm).where(ConfTerm.venue == venue))
        for prev, year in zip(years, years[1:]):
            n, m = len(by_year[year]), len(by_year[prev])
            if n < MIN_EDITION or m < MIN_EDITION:
                continue
            full = _with_abstracts(by_year[year]) and _with_abstracts(by_year[prev])
            now, before = _counts(texts(by_year[year], full)), _counts(texts(by_year[prev], full))
            scores = log_odds(now, n, before, m, prior, n_prior)
            for term in pick(scores, now, True, KEEP_RISING) + pick(scores, before, False, KEEP_FALLING):
                session.add(ConfTerm(venue=venue, year=year, term=term, papers=now.get(term, 0),
                                     share=now.get(term, 0) / n, prev_share=before.get(term, 0) / m,
                                     score=round(scores[term], 3)))
                written += 1
        session.commit()
    logger.info(f"Conference terms: {written} rows")
    return written


def for_edition(session: Session, venue: str, year: int) -> dict:
    rows = list(session.execute(select(ConfTerm).where(ConfTerm.venue == venue, ConfTerm.year == year)).scalars())
    as_dict = [{"term": r.term, "papers": r.papers, "share": r.share, "prev_share": r.prev_share, "score": r.score}
               for r in rows]
    return {"rising": sorted([t for t in as_dict if t["score"] > 0], key=lambda t: -t["score"]),
            "falling": sorted([t for t in as_dict if t["score"] < 0], key=lambda t: t["score"])}
