"""
Signal computation functions for Athena Layer 3 Scoring & Ranking.

Each function computes a single normalised score in [0.0, 1.0].
"""
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────
# 1. Citation Impact (C)
# ──────────────────────────────────────────────────────────

def compute_citation_score(citation_count: int, corpus_max: int = 500) -> float:
    """
    Log-normalised citation impact.

    Using log(1 + count) / log(1 + corpus_max) prevents papers with 10k+
    citations from drowning all others while still rewarding high citation counts.
    """
    if citation_count <= 0:
        return 0.0
    raw = math.log1p(citation_count) / math.log1p(corpus_max)
    return float(min(1.0, max(0.0, raw)))


# ──────────────────────────────────────────────────────────
# 2. Engagement & Community Reaction (E)
# ──────────────────────────────────────────────────────────

# Per-platform normalisation baselines (approximate 95th percentile values)
PLATFORM_BASELINES = {
    "lesswrong": {"karma": 200, "commentCount": 50},
    "alignmentforum": {"baseScore": 150, "commentCount": 40},
    "medium": {"clapCount": 5000, "responseCount": 100},
    "tds": {"clapCount": 5000, "responseCount": 100},
    "arxiv": {"downloadCount": 5000},
}


def _extract_engagement_signals(metadata: Dict[str, Any], source_url: str) -> List[float]:
    """Extract and normalise engagement signals from metadata based on source platform."""
    signals = []
    source_lower = source_url.lower() if source_url else ""

    if "lesswrong" in source_lower:
        baseline = PLATFORM_BASELINES["lesswrong"]
        karma = metadata.get("karma", 0) or 0
        comments = metadata.get("commentCount", 0) or 0
        signals.append(min(1.0, karma / baseline["karma"]))
        signals.append(min(1.0, comments / baseline["commentCount"]))

    elif "alignmentforum" in source_lower:
        baseline = PLATFORM_BASELINES["alignmentforum"]
        base_score = metadata.get("baseScore", 0) or 0
        comments = metadata.get("commentCount", 0) or 0
        signals.append(min(1.0, base_score / baseline["baseScore"]))
        signals.append(min(1.0, comments / baseline["commentCount"]))

    elif "medium" in source_lower or "towardsdatascience" in source_lower:
        baseline = PLATFORM_BASELINES["medium"]
        claps = metadata.get("clapCount", 0) or 0
        responses = metadata.get("responseCount", 0) or 0
        signals.append(min(1.0, claps / baseline["clapCount"]))
        signals.append(min(1.0, responses / baseline["responseCount"]))

    # Semantic Scholar / arXiv enrichment data (stored in extra_data)
    if "semantic_scholar" in metadata:
        ss = metadata["semantic_scholar"]
        if isinstance(ss, dict):
            downloads = ss.get("downloadCount", 0) or 0
            if downloads:
                signals.append(min(1.0, downloads / PLATFORM_BASELINES["arxiv"]["downloadCount"]))

    return signals


def compute_engagement_score(metadata: Dict[str, Any], source_url: str) -> float:
    """
    Compute normalised engagement score by extracting platform-specific signals
    and averaging them. Returns 0.5 (neutral) if no engagement data is available.
    """
    signals = _extract_engagement_signals(metadata or {}, source_url)
    if not signals:
        return 0.5  # Neutral default for sources with no engagement data
    return float(min(1.0, max(0.0, sum(signals) / len(signals))))


# ──────────────────────────────────────────────────────────
# 3. Recency (R)
# ──────────────────────────────────────────────────────────

def compute_recency_score(published_at: datetime, half_life_days: int = 30) -> float:
    """
    Exponential decay based on age. A paper published half_life_days ago scores 0.5.
    Formula: score = exp(-λ * age_days) where λ = ln(2) / half_life_days
    """
    if published_at is None:
        return 0.5

    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = (now - published_at).total_seconds() / 86400.0

    if age_days < 0:
        return 1.0  # Future date — treat as brand new

    decay_constant = math.log(2) / max(1, half_life_days)
    score = math.exp(-decay_constant * age_days)
    return float(min(1.0, max(0.0, score)))


# ──────────────────────────────────────────────────────────
# 4. Authority & Source Quality (A)
# ──────────────────────────────────────────────────────────

def compute_authority_score(authority_score: Optional[float]) -> float:
    """Pass-through from source.authority_score with null safety."""
    if authority_score is None:
        return 0.5
    return float(min(1.0, max(0.0, authority_score)))


# ──────────────────────────────────────────────────────────
# Composite Score
# ──────────────────────────────────────────────────────────

def compute_composite_score(
    citation: float,
    engagement: float,
    recency: float,
    authority: float,
    weights: Dict[str, float],
) -> float:
    """
    Weighted sum of the 4 signals, clipped to [0.0, 1.0].

    weights should contain keys: citation, engagement, recency, authority
    """
    raw = (
        weights.get("citation", 0.0) * citation
        + weights.get("engagement", 0.0) * engagement
        + weights.get("recency", 0.0) * recency
        + weights.get("authority", 0.0) * authority
    )
    return float(max(0.0, min(1.0, raw)))
