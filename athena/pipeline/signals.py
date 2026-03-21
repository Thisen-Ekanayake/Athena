"""
Signal computation functions for Athena Layer 3 Scoring & Ranking.

Each function computes a single normalised score in [0.0, 1.0].
"""
import math
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import numpy as np
from loguru import logger


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
    "paperswithcode": {"githubStars": 1000},
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

    elif "paperswithcode" in source_lower:
        baseline = PLATFORM_BASELINES["paperswithcode"]
        stars = metadata.get("githubStars", 0) or 0
        signals.append(min(1.0, stars / baseline["githubStars"]))

    # Semantic Scholar / arXiv enrichment data (stored in extra_data)
    if "semantic_scholar" in metadata:
        ss = metadata["semantic_scholar"]
        if isinstance(ss, dict):
            downloads = ss.get("downloadCount", 0) or 0
            if downloads:
                signals.append(min(1.0, downloads / PLATFORM_BASELINES["arxiv"]["downloadCount"]))

    if "papers_with_code" in metadata:
        pwc = metadata["papers_with_code"]
        if isinstance(pwc, dict):
            repos = pwc.get("repositories", [])
            if repos:
                total_stars = sum(r.get("stars", 0) for r in repos if isinstance(r, dict))
                signals.append(min(1.0, total_stars / PLATFORM_BASELINES["paperswithcode"]["githubStars"]))

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
# 3. Semantic Sentiment Score (S)
# ──────────────────────────────────────────────────────────

# Reference phrases for cosine similarity comparison
POSITIVE_POLES = [
    "This is a significant breakthrough",
    "Must-read for anyone in ML",
    "Groundbreaking results",
    "This changes how we think about the problem",
    "Excellent methodology and compelling evidence",
    "Important contribution to the field",
    "Highly recommended reading",
    "Novel and impactful work",
    "State of the art results",
    "Brilliant insight and rigorous analysis",
]

NEGATIVE_POLES = [
    "This is not novel",
    "Incremental work at best",
    "Disappointing results",
    "Overhyped and underdelivers",
    "Poor methodology and weak evidence",
    "Nothing new in this paper",
    "Misleading claims",
    "Failed to replicate",
    "Marginal improvement at best",
    "Trivial contribution",
]

# Cached reference embeddings (computed once, reused)
_cached_positive_embeddings: Optional[np.ndarray] = None
_cached_negative_embeddings: Optional[np.ndarray] = None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _get_reference_embeddings(openai_client) -> tuple:
    """Get or compute reference pole embeddings (cached in module globals)."""
    global _cached_positive_embeddings, _cached_negative_embeddings

    if _cached_positive_embeddings is not None and _cached_negative_embeddings is not None:
        return _cached_positive_embeddings, _cached_negative_embeddings

    try:
        pos_response = openai_client.embeddings.create(
            input=POSITIVE_POLES,
            model="text-embedding-3-small"
        )
        neg_response = openai_client.embeddings.create(
            input=NEGATIVE_POLES,
            model="text-embedding-3-small"
        )

        _cached_positive_embeddings = np.array([d.embedding for d in pos_response.data])
        _cached_negative_embeddings = np.array([d.embedding for d in neg_response.data])

        return _cached_positive_embeddings, _cached_negative_embeddings
    except Exception as e:
        logger.error(f"Failed to compute reference embeddings: {e}")
        return None, None


def _extract_comments(metadata: Dict[str, Any]) -> List[str]:
    """Extract comment texts from metadata JSONB."""
    comments = []

    # LessWrong / AI Alignment Forum structured comments
    if "comments" in metadata and isinstance(metadata["comments"], list):
        for c in metadata["comments"]:
            if isinstance(c, dict):
                text = c.get("body", "") or c.get("text", "") or c.get("htmlBody", "")
                if text:
                    comments.append(str(text)[:500])
            elif isinstance(c, str):
                comments.append(c[:500])

    # Generic comment field
    if "comment_texts" in metadata and isinstance(metadata["comment_texts"], list):
        comments.extend([str(c)[:500] for c in metadata["comment_texts"] if c])

    return comments


def compute_sentiment_score(
    metadata: Dict[str, Any],
    openai_client=None,
) -> float:
    """
    Compute semantic sentiment by embedding comments and comparing cosine
    similarity to positive/negative reference poles.

    Returns 0.5 (neutral) if no comments are available or if embedding fails.
    """
    comments = _extract_comments(metadata or {})
    if not comments:
        return 0.5

    if openai_client is None:
        return 0.5

    try:
        pos_embeds, neg_embeds = _get_reference_embeddings(openai_client)
        if pos_embeds is None or neg_embeds is None:
            return 0.5

        # Embed comments in batches of 50
        all_comment_embeds = []
        for i in range(0, len(comments), 50):
            batch = comments[i:i + 50]
            response = openai_client.embeddings.create(
                input=batch,
                model="text-embedding-3-small"
            )
            all_comment_embeds.extend([d.embedding for d in response.data])

        comment_embeddings = np.array(all_comment_embeds)

        # For each comment, compute mean similarity to positive pole
        positive_similarities = []
        for comment_emb in comment_embeddings:
            sims = [_cosine_similarity(comment_emb, pos) for pos in pos_embeds]
            positive_similarities.append(np.mean(sims))

        # Mean across all comments
        sentiment = float(np.mean(positive_similarities))
        return min(1.0, max(0.0, sentiment))

    except Exception as e:
        logger.error(f"Sentiment computation failed: {e}")
        return 0.5


# ──────────────────────────────────────────────────────────
# 4. Recency & Velocity (R)
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


def compute_velocity_score(
    current_citations: int,
    current_engagement: float,
    prev_citations: int,
    prev_engagement: float,
    max_citation_delta: int = 50,
    max_engagement_delta: float = 0.3,
) -> float:
    """
    Velocity = rate of change in citation count + engagement over the last 7 days.
    Normalised against reasonable maxima.
    """
    citation_delta = max(0, current_citations - prev_citations)
    engagement_delta = max(0.0, current_engagement - prev_engagement)

    citation_velocity = min(1.0, citation_delta / max(1, max_citation_delta))
    engagement_velocity = min(1.0, engagement_delta / max(0.01, max_engagement_delta))

    # 60/40 split between citation velocity and engagement velocity
    combined = 0.6 * citation_velocity + 0.4 * engagement_velocity
    return float(min(1.0, max(0.0, combined)))


# ──────────────────────────────────────────────────────────
# 5. Authority & Source Quality (A)
# ──────────────────────────────────────────────────────────

def compute_authority_score(authority_score: Optional[float]) -> float:
    """Pass-through from source.authority_score with null safety."""
    if authority_score is None:
        return 0.5
    return float(min(1.0, max(0.0, authority_score)))


# ──────────────────────────────────────────────────────────
# Composite Score & Trending
# ──────────────────────────────────────────────────────────

def compute_composite_score(
    citation: float,
    engagement: float,
    sentiment: float,
    recency: float,
    authority: float,
    weights: Dict[str, float],
) -> float:
    """
    Weighted sum of all 5 signals, clipped to [0.0, 1.0].

    weights should contain keys: citation, engagement, sentiment, recency, authority
    """
    raw = (
        weights.get("citation", 0.30) * citation
        + weights.get("engagement", 0.15) * engagement
        + weights.get("sentiment", 0.15) * sentiment
        + weights.get("recency", 0.20) * recency
        + weights.get("authority", 0.20) * authority
    )
    return float(max(0.0, min(1.0, raw)))


def apply_trending_boost(base_score: float, is_trending: bool) -> float:
    """
    Trending items receive a +0.08 boost, capped at 0.95.
    Keeps truly seminal older work still reachable at top.
    """
    if not is_trending:
        return base_score
    return min(0.95, base_score + 0.08)


def check_trending_criteria(
    velocity_score: float,
    published_at: datetime,
    engagement_data_points: int,
    max_age_days: int = 30,
    velocity_threshold: float = 0.70,
    min_engagement_points: int = 3,
) -> bool:
    """
    Determine if an item qualifies as trending:
    - velocity_score > threshold (~top 5%)
    - Published within last max_age_days
    - Has at least min_engagement_points engagement signals
    """
    if velocity_score <= velocity_threshold:
        return False

    now = datetime.now(timezone.utc)
    if published_at is None:
        return False
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age_days = (now - published_at).total_seconds() / 86400.0
    if age_days > max_age_days:
        return False

    if engagement_data_points < min_engagement_points:
        return False

    return True
