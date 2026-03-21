"""
Unit tests for Athena Layer 3 Scoring & Ranking.

Covers:
- Log normalisation formula correctness
- Engagement extraction per platform
- Sentiment score with mock embeddings
- Recency exponential decay formula
- Weight application and score clipping
- Trending boost logic
- Composite score computation
- Velocity score computation
- Authority score pass-through
- Cosine similarity
"""
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest
import numpy as np

from athena.pipeline.signals import (
    compute_citation_score,
    compute_engagement_score,
    compute_sentiment_score,
    compute_recency_score,
    compute_velocity_score,
    compute_authority_score,
    compute_composite_score,
    apply_trending_boost,
    check_trending_criteria,
    _extract_engagement_signals,
    _cosine_similarity,
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
# Sentiment Score Tests
# ─────────────────────────────────────────────────────────

class TestSentimentScore:
    def test_no_comments_returns_neutral(self):
        assert compute_sentiment_score({}) == 0.5

    def test_no_openai_client_returns_neutral(self):
        metadata = {"comments": [{"body": "Great paper!"}]}
        assert compute_sentiment_score(metadata, openai_client=None) == 0.5

    def test_empty_comments_list(self):
        assert compute_sentiment_score({"comments": []}) == 0.5

    def test_with_mock_openai_client(self):
        """Test sentiment with mock embeddings."""
        mock_client = MagicMock()

        # Mock reference embeddings
        pos_embedding = np.array([1.0, 0.0, 0.0] * 512)  # 1536-dim
        neg_embedding = np.array([0.0, 1.0, 0.0] * 512)
        comment_embedding = np.array([0.8, 0.2, 0.0] * 512)  # closer to positive

        pos_response = MagicMock()
        pos_response.data = [MagicMock(embedding=pos_embedding.tolist()) for _ in range(10)]

        neg_response = MagicMock()
        neg_response.data = [MagicMock(embedding=neg_embedding.tolist()) for _ in range(10)]

        comment_response = MagicMock()
        comment_response.data = [MagicMock(embedding=comment_embedding.tolist())]

        mock_client.embeddings.create = MagicMock(side_effect=[
            pos_response, neg_response, comment_response
        ])

        # Reset cache
        import athena.pipeline.signals as signals_mod
        signals_mod._cached_positive_embeddings = None
        signals_mod._cached_negative_embeddings = None

        metadata = {"comments": [{"body": "Excellent breakthrough!"}]}
        score = compute_sentiment_score(metadata, mock_client)
        assert 0.0 <= score <= 1.0


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
# Velocity Score Tests
# ─────────────────────────────────────────────────────────

class TestVelocityScore:
    def test_no_change(self):
        assert compute_velocity_score(10, 0.5, 10, 0.5) == 0.0

    def test_citation_increase(self):
        score = compute_velocity_score(60, 0.5, 10, 0.5)
        assert score > 0.0

    def test_engagement_increase(self):
        score = compute_velocity_score(10, 0.8, 10, 0.5)
        assert score > 0.0

    def test_max_velocity(self):
        score = compute_velocity_score(100, 1.0, 0, 0.0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_negative_delta_treated_as_zero(self):
        """Decreasing metrics shouldn't produce negative velocity."""
        score = compute_velocity_score(5, 0.3, 10, 0.5)
        assert score == 0.0

    def test_60_40_split(self):
        """Citation velocity is weighted 60%, engagement 40%."""
        # Only citation change
        s_cit = compute_velocity_score(50, 0.0, 0, 0.0)
        # Only engagement change
        s_eng = compute_velocity_score(0, 0.3, 0, 0.0)
        # Citation should contribute more per unit
        assert s_cit > s_eng


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
        weights = {"citation": 0.3, "engagement": 0.15, "sentiment": 0.15,
                   "recency": 0.2, "authority": 0.2}
        assert compute_composite_score(0, 0, 0, 0, 0, weights) == 0.0

    def test_all_ones(self):
        weights = {"citation": 0.3, "engagement": 0.15, "sentiment": 0.15,
                   "recency": 0.2, "authority": 0.2}
        score = compute_composite_score(1.0, 1.0, 1.0, 1.0, 1.0, weights)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_clipped_to_unit_range(self):
        weights = {"citation": 0.5, "engagement": 0.5, "sentiment": 0.5,
                   "recency": 0.5, "authority": 0.5}
        # Sum of weights is 2.5, all signals at 1.0 = 2.5, but should clip to 1.0
        score = compute_composite_score(1.0, 1.0, 1.0, 1.0, 1.0, weights)
        assert score == 1.0

    def test_weights_affect_ranking(self):
        """An item with high citation but low recency should rank differently
        depending on the weight profile."""
        paper_weights = {"citation": 0.30, "engagement": 0.15, "sentiment": 0.15,
                         "recency": 0.20, "authority": 0.20}
        blog_weights = {"citation": 0.10, "engagement": 0.30, "sentiment": 0.20,
                        "recency": 0.25, "authority": 0.15}

        # Item with high citation, low engagement
        s_paper = compute_composite_score(0.9, 0.2, 0.5, 0.3, 0.8, paper_weights)
        s_blog = compute_composite_score(0.9, 0.2, 0.5, 0.3, 0.8, blog_weights)
        # Paper weights favor citation more, so should score higher for this item
        assert s_paper > s_blog

    def test_default_weights_used(self):
        """Empty weights dict should use defaults."""
        score = compute_composite_score(0.5, 0.5, 0.5, 0.5, 0.5, {})
        expected = 0.3 * 0.5 + 0.15 * 0.5 + 0.15 * 0.5 + 0.2 * 0.5 + 0.2 * 0.5
        assert score == pytest.approx(expected, abs=0.01)


# ─────────────────────────────────────────────────────────
# Trending Tests
# ─────────────────────────────────────────────────────────

class TestTrending:
    def test_boost_not_applied_when_not_trending(self):
        assert apply_trending_boost(0.8, False) == 0.8

    def test_boost_applied(self):
        assert apply_trending_boost(0.8, True) == 0.88

    def test_boost_capped_at_095(self):
        assert apply_trending_boost(0.92, True) == 0.95

    def test_boost_exactly_at_cap(self):
        assert apply_trending_boost(0.87, True) == 0.95

    def test_trending_criteria_met(self):
        published = datetime.now(timezone.utc) - timedelta(days=5)
        assert check_trending_criteria(0.8, published, 5) is True

    def test_trending_low_velocity(self):
        published = datetime.now(timezone.utc) - timedelta(days=5)
        assert check_trending_criteria(0.5, published, 5) is False

    def test_trending_too_old(self):
        published = datetime.now(timezone.utc) - timedelta(days=60)
        assert check_trending_criteria(0.8, published, 5) is False

    def test_trending_too_few_signals(self):
        published = datetime.now(timezone.utc) - timedelta(days=5)
        assert check_trending_criteria(0.8, published, 1) is False

    def test_trending_none_published_at(self):
        assert check_trending_criteria(0.8, None, 5) is False


# ─────────────────────────────────────────────────────────
# Cosine Similarity Tests
# ─────────────────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        assert _cosine_similarity(v1, v2) == pytest.approx(0.0, abs=1e-6)

    def test_zero_vector(self):
        v1 = np.array([1.0, 2.0, 3.0])
        v2 = np.array([0.0, 0.0, 0.0])
        assert _cosine_similarity(v1, v2) == 0.0

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([-1.0, 0.0])
        assert _cosine_similarity(v1, v2) == pytest.approx(-1.0, abs=1e-6)


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
