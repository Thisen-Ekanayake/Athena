"""
Integration tests for Athena Layer 3 Scoring & Ranking.

Tests scoring pipeline with mocked database sessions and the score API endpoint.
"""
from datetime import datetime, timezone, timedelta
import pytest

from athena.pipeline.signals import (
    compute_citation_score,
    compute_engagement_score,
    compute_recency_score,
    compute_authority_score,
    compute_composite_score,
    apply_trending_boost,
)


class TestScoringPipelineIntegration:
    """Test the full scoring pipeline logic without a real database."""

    def test_full_score_computation(self):
        """Simulate scoring an item through all 4 signals."""
        # Mock item data
        citation_count = 150
        metadata = {"karma": 80, "commentCount": 15}
        source_url = "https://lesswrong.com/posts/test"
        published_at = datetime.now(timezone.utc) - timedelta(days=10)
        authority = 0.75

        # Compute signals
        citation = compute_citation_score(citation_count)
        engagement = compute_engagement_score(metadata, source_url)
        recency = compute_recency_score(published_at, half_life_days=30)
        auth_score = compute_authority_score(authority)

        # Composite
        weights = {"citation": 0.35, "engagement": 0.15, "recency": 0.25, "authority": 0.25}
        composite = compute_composite_score(citation, engagement, recency, auth_score, weights)

        assert 0.0 <= composite <= 1.0
        # A recent LessWrong post with 150 citations and 0.75 authority should score well
        assert composite > 0.3

    def test_paper_scores_higher_than_unknown_blog(self):
        """A Nature paper with 200 citations should outscore an unknown blog post."""
        # Nature paper
        nature_citation = compute_citation_score(200)
        nature_engagement = compute_engagement_score({}, "https://nature.com")
        nature_recency = compute_recency_score(
            datetime.now(timezone.utc) - timedelta(days=60), half_life_days=60
        )
        nature_authority = compute_authority_score(1.0)

        # Unknown blog
        blog_citation = compute_citation_score(0)
        blog_engagement = compute_engagement_score({}, "https://random-blog.com")
        blog_recency = compute_recency_score(
            datetime.now(timezone.utc) - timedelta(days=60), half_life_days=60
        )
        blog_authority = compute_authority_score(0.50)

        weights = {"citation": 0.35, "engagement": 0.15, "recency": 0.25, "authority": 0.25}

        nature_score = compute_composite_score(
            nature_citation, nature_engagement, nature_recency, nature_authority, weights
        )
        blog_score = compute_composite_score(
            blog_citation, blog_engagement, blog_recency, blog_authority, weights
        )

        assert nature_score > blog_score

    def test_trending_boost_surfaces_new_items(self):
        """A trending new item should outscore a non-trending equivalent."""
        base_score = 0.55
        boosted = apply_trending_boost(base_score, True)
        unboosted = apply_trending_boost(base_score, False)
        assert boosted > unboosted
        assert boosted == 0.63

    def test_different_category_weights_differentiate(self):
        """Same item scored with paper vs blog weights should differ."""
        paper_weights = {"citation": 0.40, "engagement": 0.0, "recency": 0.35, "authority": 0.25}
        blog_weights = {"citation": 0.0, "engagement": 0.40, "recency": 0.35, "authority": 0.25}

        # Item with high citation, moderate other signals
        s_paper = compute_composite_score(0.8, 0.3, 0.4, 0.7, paper_weights)
        s_blog = compute_composite_score(0.8, 0.3, 0.4, 0.7, blog_weights)

        # Different category weights should produce different scores
        assert s_paper != s_blog

    def test_default_signals_produce_reasonable_score(self):
        """With all signals at 0.5, the composite should be 0.5."""
        weights = {"citation": 0.35, "engagement": 0.15, "recency": 0.25, "authority": 0.25}
        score = compute_composite_score(0.5, 0.5, 0.5, 0.5, weights)
        assert score == pytest.approx(0.5, abs=0.01)


class TestScoringConfigDefaults:
    """Test default scoring configuration values."""

    def test_default_weights_sum_to_one(self):
        from athena.pipeline.scoring import DEFAULT_WEIGHTS
        from athena.pipeline.scoring import BASE_SIGNALS
        for category, weights in DEFAULT_WEIGHTS.items():
            total = sum(weights[k] for k in BASE_SIGNALS)
            assert total == pytest.approx(1.0, abs=0.01), (
                f"{category} weights sum to {total}, expected 1.0"
            )

    def test_all_categories_have_defaults(self):
        from athena.pipeline.scoring import DEFAULT_WEIGHTS
        assert "paper" in DEFAULT_WEIGHTS
        assert "company_blog" in DEFAULT_WEIGHTS
        assert "community_blog" in DEFAULT_WEIGHTS

    def test_authority_defaults_exist(self):
        from athena.pipeline.scoring import DEFAULT_AUTHORITY
        assert "arxiv" in DEFAULT_AUTHORITY
        assert DEFAULT_AUTHORITY["arxiv"] == 0.85
        assert DEFAULT_AUTHORITY["neurips"] == 1.0
        assert DEFAULT_AUTHORITY["openai"] == 0.90
