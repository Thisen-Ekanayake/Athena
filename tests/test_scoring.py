"""
Unit tests for Athena Layer 3 Scoring & Ranking.

Covers:
- Log normalisation formula correctness
- Engagement extraction per platform
- Recency exponential decay formula
- Weight application and score clipping
- Composite score computation
- Authority score pass-through
"""
import math
from datetime import datetime, timezone, timedelta
import pytest

from athena.pipeline.signals import (
    compute_citation_score,
    compute_engagement_score,
    compute_recency_score,
    compute_authority_score,
    compute_composite_score,
    _extract_engagement_signals,
)


# ─────────────────────────────────────────────────────────
# Citation Score Tests
# ─────────────────────────────────────────────────────────

class TestCitationScore:
    def test_zero_citations(self):
        assert compute_citation_score(0) == 0.0

    def test_negative_citations(self):
        assert compute_citation_score(-5) == 0.0

    def test_positive_citations(self):
        score = compute_citation_score(100)
        assert 0.0 < score < 1.0

    def test_high_citations_approaches_one(self):
        score = compute_citation_score(500)  # corpus_max default
        assert score == pytest.approx(1.0, abs=0.01)

    def test_log_normalisation_ordering(self):
        """Higher citation counts should yield higher scores."""
        s1 = compute_citation_score(10)
        s2 = compute_citation_score(100)
        s3 = compute_citation_score(500)
        assert s1 < s2 < s3

    def test_log_prevents_domination(self):
        """A 10k-citation paper shouldn't score dramatically more than 500."""
        s_500 = compute_citation_score(500)
        s_10000 = compute_citation_score(10000)
        # The difference should be bounded (not 20x)
        assert s_10000 - s_500 < 0.5

    def test_clipped_to_unit(self):
        """Score should never exceed 1.0."""
        assert compute_citation_score(100000) <= 1.0

    def test_formula_correctness(self):
        """Verify the log formula directly."""
        score = compute_citation_score(100, corpus_max=500)
        expected = math.log1p(100) / math.log1p(500)
        assert score == pytest.approx(expected, abs=1e-6)


# ─────────────────────────────────────────────────────────
# Engagement Score Tests
# ─────────────────────────────────────────────────────────

class TestEngagementScore:
    def test_no_metadata(self):
        """No metadata should return neutral 0.5."""
        assert compute_engagement_score({}, "") == 0.5

    def test_lesswrong_engagement(self):
        metadata = {"karma": 100, "commentCount": 20}
        score = compute_engagement_score(metadata, "https://lesswrong.com/posts/abc")
        assert 0.0 < score < 1.0

    def test_lesswrong_high_karma(self):
        metadata = {"karma": 200, "commentCount": 50}
        score = compute_engagement_score(metadata, "https://lesswrong.com/posts/abc")
        assert score == pytest.approx(1.0, abs=0.01)

    def test_medium_engagement(self):
        metadata = {"clapCount": 2500, "responseCount": 50}
        score = compute_engagement_score(metadata, "https://medium.com/post")
        assert 0.0 < score < 1.0

    def test_alignment_forum(self):
        metadata = {"baseScore": 75, "commentCount": 20}
        score = compute_engagement_score(metadata, "https://alignmentforum.org/posts/abc")
        assert 0.0 < score < 1.0

    def test_papers_with_code(self):
        metadata = {"githubStars": 500}
        score = compute_engagement_score(metadata, "https://paperswithcode.com/paper/test")
        assert 0.0 < score < 1.0

    def test_unknown_source_returns_neutral(self):
        metadata = {"random_field": 42}
        score = compute_engagement_score(metadata, "https://unknown-source.com")
        assert score == 0.5

    def test_null_values_handled(self):
        metadata = {"karma": None, "commentCount": None}
        score = compute_engagement_score(metadata, "https://lesswrong.com")
        assert score == 0.0  # Both signals are 0

    def test_tds_engagement(self):
        metadata = {"clapCount": 1000, "responseCount": 25}
        score = compute_engagement_score(metadata, "https://towardsdatascience.com/post")
        assert 0.0 < score < 1.0

    def test_semantic_scholar_enrichment(self):
        metadata = {"semantic_scholar": {"downloadCount": 2500}}
        score = compute_engagement_score(metadata, "https://arxiv.org/abs/123")
        assert 0.0 < score < 1.0


# ─────────────────────────────────────────────────────────
# Recency Score Tests
# ─────────────────────────────────────────────────────────

class TestRecencyScore:
    def test_brand_new_paper(self):
        """Paper published just now should score ~1.0."""
        now = datetime.now(timezone.utc)
        score = compute_recency_score(now, half_life_days=30)
        assert score == pytest.approx(1.0, abs=0.05)

    def test_half_life_paper(self):
        """Paper published exactly half_life_days ago should score ~0.5."""
        published = datetime.now(timezone.utc) - timedelta(days=30)
        score = compute_recency_score(published, half_life_days=30)
        assert score == pytest.approx(0.5, abs=0.05)

    def test_old_paper(self):
        """Paper published 180 days ago should score very low."""
        published = datetime.now(timezone.utc) - timedelta(days=180)
        score = compute_recency_score(published, half_life_days=30)
        assert score < 0.1

    def test_future_date(self):
        """Future date should score 1.0."""
        future = datetime.now(timezone.utc) + timedelta(days=5)
        assert compute_recency_score(future) == 1.0

    def test_none_published_at(self):
        """None published_at should return neutral 0.5."""
        assert compute_recency_score(None) == 0.5

    def test_naive_datetime_handled(self):
        """Naive datetime (no timezone) should be handled gracefully."""
        published = datetime.utcnow() - timedelta(days=15)
        score = compute_recency_score(published, half_life_days=30)
        assert 0.0 <= score <= 1.0

    def test_exponential_decay_formula(self):
        """Verify the formula matches exp(-λ*t)."""
        half_life = 30
        age_days = 10
        published = datetime.now(timezone.utc) - timedelta(days=age_days)
        score = compute_recency_score(published, half_life)
        expected = math.exp(-math.log(2) / half_life * age_days)
        assert score == pytest.approx(expected, abs=0.05)


# ─────────────────────────────────────────────────────────
# Authority Score Tests
# ─────────────────────────────────────────────────────────

class TestAuthorityScore:
    def test_none_returns_neutral(self):
        assert compute_authority_score(None) == 0.5

    def test_pass_through(self):
        assert compute_authority_score(0.85) == 0.85

    def test_clipped_high(self):
        assert compute_authority_score(1.5) == 1.0

    def test_clipped_low(self):
        assert compute_authority_score(-0.1) == 0.0


# ─────────────────────────────────────────────────────────
# Composite Score Tests
# ─────────────────────────────────────────────────────────

class TestCompositeScore:
    def test_all_zeros(self):
        weights = {"citation": 0.35, "engagement": 0.15, "recency": 0.25, "authority": 0.25}
        assert compute_composite_score(0, 0, 0, 0, weights) == 0.0

    def test_all_ones(self):
        weights = {"citation": 0.35, "engagement": 0.15, "recency": 0.25, "authority": 0.25}
        score = compute_composite_score(1.0, 1.0, 1.0, 1.0, weights)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_clipped_to_unit_range(self):
        weights = {"citation": 0.5, "engagement": 0.5, "recency": 0.5, "authority": 0.5}
        # Sum of weights is 2.0, all signals at 1.0 = 2.0, but should clip to 1.0
        score = compute_composite_score(1.0, 1.0, 1.0, 1.0, weights)
        assert score == 1.0

    def test_weights_affect_ranking(self):
        """An item with high citation but low recency should rank differently
        depending on the weight profile."""
        paper_weights = {"citation": 0.40, "engagement": 0.0, "recency": 0.35, "authority": 0.25}
        blog_weights = {"citation": 0.0, "engagement": 0.40, "recency": 0.35, "authority": 0.25}

        # Item with high citation, low engagement
        s_paper = compute_composite_score(0.9, 0.2, 0.3, 0.8, paper_weights)
        s_blog = compute_composite_score(0.9, 0.2, 0.3, 0.8, blog_weights)
        # Paper weights favor citation more, so should score higher for this item
        assert s_paper > s_blog

    def test_missing_weight_counts_for_nothing(self):
        """A signal without a weight adds nothing to the score."""
        assert compute_composite_score(0.5, 0.5, 0.5, 0.5, {}) == 0.0
        assert compute_composite_score(0.5, 1.0, 0.5, 0.5, {"engagement": 0.4}) == pytest.approx(0.4)


# ─────────────────────────────────────────────────────────
# Engagement Signal Extraction Tests
# ─────────────────────────────────────────────────────────

class TestEngagementExtraction:
    def test_extract_lesswrong_signals(self):
        metadata = {"karma": 100, "commentCount": 25}
        signals = _extract_engagement_signals(metadata, "https://lesswrong.com/posts/abc")
        assert len(signals) == 2
        assert all(0 <= s <= 1 for s in signals)

    def test_extract_empty_metadata(self):
        signals = _extract_engagement_signals({}, "")
        assert len(signals) == 0

    def test_extract_enrichment_data(self):
        metadata = {
            "semantic_scholar": {"downloadCount": 1000},
            "papers_with_code": {"repositories": [{"stars": 200}]}
        }
        signals = _extract_engagement_signals(metadata, "https://arxiv.org/abs/123")
        assert len(signals) >= 1
