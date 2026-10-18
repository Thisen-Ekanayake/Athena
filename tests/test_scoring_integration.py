"""
Integration tests for feed scoring and ranking.

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


class TestDefaultAuthority:
    """Sources get their publisher's authority at setup and when added (ROADMAP_v2 T1)."""

    @pytest.mark.parametrize("url, expected", [
        ("https://export.arxiv.org/api/query", 0.85),
        ("https://openai.com/news/rss.xml", 0.90),
        ("https://ai.meta.com/blog", 0.90),
        ("https://www.microsoft.com/en-us/research/feed/", 0.85),
        ("https://huggingface.co/blog/feed.xml", 0.80),
        ("https://blogs.nvidia.com/feed/", 0.70),
        ("https://x.ai/news", 0.70),
        ("https://thegradient.pub/", 0.75),
        ("https://metaculus.com/feed", None),  # "meta" alone no longer matches
        ("https://max.ai/blog", None),  # a domain key matches that host, not any host ending in it
        ("https://example.com/", None),
    ])
    def test_default_authority_by_url(self, url, expected):
        from athena.pipeline.scoring import default_authority
        assert default_authority(url) == expected

    def test_populate_keeps_values_set_by_hand(self, monkeypatch):
        from uuid import uuid4
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from athena.core.models import Source, SourceCategory, SourceType
        from athena.pipeline import scoring

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Source.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr(scoring, "SessionLocal", Session)
        urls = {"neutral": "https://huggingface.co/blog/feed.xml", "hand": "https://openai.com/news/rss.xml",
                "unknown": "https://example.com/feed", "later": "https://blogs.nvidia.com/feed/"}
        ids = {k: uuid4() for k in urls}
        with Session() as s:
            for key, url in urls.items():
                s.add(Source(id=ids[key], name=key, url=url, type=SourceType.RSS, category=SourceCategory.COMPANY,
                             authority_score=0.3 if key == "hand" else 0.5))
            s.commit()

        assert scoring.populate_default_authority_scores(ids["neutral"]) == 1  # only the one asked for
        assert scoring.populate_default_authority_scores() == 1  # then the rest: nvidia
        with Session() as s:
            got = {src.name: src.authority_score for src in s.query(Source).all()}
        assert got == {"neutral": 0.80, "hand": 0.3, "unknown": 0.5, "later": 0.70}
