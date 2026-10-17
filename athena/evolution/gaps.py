"""
Phase 3: gap themes for a topic.

A topic's gap statements (a paper's own limitations, and limitations later
papers state about it) are clustered by meaning, so "LoRA cannot be merged
after quantization" and "quantized adapters lose accuracy when merged" land
in one theme. Each theme gets:

- a label from its most distinctive words (class-based TF-IDF: the words
  that are frequent in this theme and rare in the topic's other themes);
- how many statements each year, by the year the stating paper appeared;
- a status: ``addressed`` when a strict link claims a fix; otherwise
  ``persisting`` when it is still stated in the topic's last two years and
  was first stated before them, ``new`` when it has only been stated in
  them, and ``quiet`` when it has not been stated in them.

Pure functions; ``athena.evolution.model_lane`` feeds them vectors from Qdrant.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

THEME_DISTANCE = 0.40   # average-linkage cosine distance at which clusters stop merging (see below)
# Chosen on the first run's three topics: at 0.35 PEFT split "high cost of full fine-tuning" into three
# themes and 69% of statements were themed; at 0.40 they merge and 82% are; from 0.45 themes blur together
# (PEFT's largest grew to 89 statements, at 0.50 to 286).
MIN_THEME_SIZE = 3
RECENT_YEARS = 2
LABEL_TERMS = 3
# Words every gap statement uses; they say nothing about which gap it is.
_GENERIC = {
    "method", "methods", "model", "models", "approach", "approaches", "work", "works", "paper", "papers", "propose",
    "proposed", "however", "existing", "previous", "prior", "results", "result", "performance", "problem",
    "problems", "limitation", "limitations", "limited", "future", "use", "used", "using", "based", "also", "may",
    "can", "cannot", "et", "al", "et al", "issue", "issues", "lack", "require", "requires", "remain", "remains",
    "still", "often", "usually", "suffer", "suffers", "fail", "fails", "challenge", "challenging", "task", "tasks",
    "shown", "show", "shows", "study", "studies", "recent", "recently", "different", "able", "unable", "need",
    "needs", "make", "makes", "does", "important", "significant", "significantly", "large", "small", "high", "low",
    "better", "best", "new", "like", "way", "ways", "time", "number", "difficult", "address", "addressed",
    "techniques", "technique", "framework", "frameworks", "paradigm", "setting", "settings",
}
STOP_WORDS = list(ENGLISH_STOP_WORDS | _GENERIC)
# Citation markers and section numbers, removed before labelling so author names do not become labels.
_CITATIONS = re.compile(r"\([^()]*?(?:19|20)\d{2}[a-z]?[^()]*\)|\[[\d,;\s–-]+\]|\bet al\.?|^\s*\d+(\.\d+)*\s+")


def _clean(sentence: str) -> str:
    return _CITATIONS.sub(" ", sentence)


def cluster(vectors: np.ndarray, distance: float = THEME_DISTANCE, min_size: int = MIN_THEME_SIZE) -> list[int]:
    """Cluster index per vector, or -1 for statements in clusters smaller than ``min_size``."""
    if len(vectors) < min_size:
        return [-1] * len(vectors)
    labels = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=distance).fit_predict(vectors)
    sizes = Counter(labels)
    keep = sorted((c for c, n in sizes.items() if n >= min_size), key=lambda c: -sizes[c])
    renumber = {c: i for i, c in enumerate(keep)}
    return [renumber.get(c, -1) for c in labels]


def theme_terms(docs_by_theme: dict[int, list[str]], n: int = LABEL_TERMS) -> dict[int, list[str]]:
    """Each theme's most distinctive words and two-word phrases (class-based TF-IDF)."""
    themes = sorted(docs_by_theme)
    if not themes:
        return {}
    vectorizer = CountVectorizer(stop_words=STOP_WORDS, ngram_range=(1, 2), min_df=1,
                                 token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b")
    try:
        counts = vectorizer.fit_transform([" ".join(docs_by_theme[t]) for t in themes]).toarray().astype(float)
    except ValueError:  # every word was a stop word
        return {t: [] for t in themes}
    words = vectorizer.get_feature_names_out()
    tf = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    avg_words = counts.sum() / len(themes)
    idf = np.log(1 + avg_words / np.maximum(counts.sum(axis=0), 1))
    scores = tf * idf
    out = {}
    for row, theme in enumerate(themes):
        picked: list[str] = []
        # Highest score first; on a tie the two-word phrase, which says more than either word.
        for i in sorted(range(len(words)), key=lambda i: (-scores[row, i], -len(words[i].split()), words[i])):
            if counts[row, i] < 2 or scores[row, i] <= 0:
                break
            if any(set(words[i].split()) & set(p.split()) for p in picked):
                continue  # shares a word with a term already picked
            picked.append(words[i])
            if len(picked) == n:
                break
        out[theme] = picked
    return out


def build_themes(rows: list[dict], vectors: np.ndarray, distance: float = THEME_DISTANCE,
                 min_size: int = MIN_THEME_SIZE) -> list[dict]:
    """Themes from gap statements.

    ``rows``: dicts with id, paper_id, source_paper_id, origin (own | citing), sentence, year and fix (whether
    a strict link claims to fix it), aligned with ``vectors``.
    """
    labels = cluster(vectors, distance, min_size)
    members: dict[int, list[dict]] = defaultdict(list)
    for row, label in zip(rows, labels):
        if label >= 0:
            members[label].append(row)
    terms = theme_terms({t: [_clean(r["sentence"]) for r in rs] for t, rs in members.items()})
    years = [r["year"] for r in rows if r["year"]]
    latest = max(years) if years else None

    themes = []
    for t, rs in members.items():
        yearly = Counter(r["year"] for r in rs if r["year"])
        first, last = (min(yearly), max(yearly)) if yearly else (None, None)
        fixes = [r for r in rs if r["fix"]]
        window = latest - (RECENT_YEARS - 1) if latest is not None else None
        recent = window is not None and last is not None and last >= window
        if fixes:
            status = "addressed"
        elif recent:
            status = "persisting" if first is not None and first < window else "new"
        else:
            status = "quiet"
        papers = Counter(r["paper_id"] for r in rs)
        themes.append({
            "label": " · ".join(terms.get(t) or ["(no distinctive words)"]),
            "size": len(rs),
            "yearly": {str(y): n for y, n in sorted(yearly.items())},
            "first_year": first,
            "last_year": last,
            "status": status,
            "detail": {
                "terms": terms.get(t, []),
                "own": sum(r["origin"] == "own" for r in rs),
                "citing": sum(r["origin"] == "citing" for r in rs),
                "papers": [str(p) for p, _ in papers.most_common(8)],
                "fixed_by": sorted({str(r["source_paper_id"]) for r in fixes}),
                "latest_topic_year": latest,
            },
            "members": [r["id"] for r in rs],
        })
    order = {"persisting": 0, "new": 1, "addressed": 2, "quiet": 3}
    return sorted(themes, key=lambda th: (order[th["status"]], -th["size"]))
