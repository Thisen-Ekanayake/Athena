"""
Athena Layer 5 — API Tests

Unit and integration tests for all Layer 5 API endpoints using TestClient.
"""
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from datetime import datetime, timezone

from athena.api.main import app
from athena.api.deps import get_db, get_redis
from athena.core.models import (
    ContentItem, Source, Cluster, SummaryStatus, ContentCategory, SourceType, SourceCategory, ContentScore
)

client = TestClient(app)


# ── Mocks ─────────────────────────────────────────────────────────────

class MockRedis:
    """Simple in-memory mock for Redis caching."""
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, time, value):
        self.store[key] = value

    def scan_iter(self, match, count=100):
        # Very basic glob match (just checking start/end for simplicity in tests)
        import fnmatch
        return [k for k in self.store.keys() if fnmatch.fnmatch(k, match)]

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.store:
                self.store.pop(k, None)
                count += 1
        return count


class MockSession:
    """Mock SQLAlchemy Session."""
    def __init__(self, data):
        self._data = data
        self._query_result = []

    def execute(self, stmt):
        class Result:
            def __init__(self, items):
                self._items = items

            def scalar(self):
                return self._items[0] if self._items else None

            def scalar_one_or_none(self):
                return self._items[0] if self._items else None

            def scalar_one(self):
                if not self._items:
                    raise Exception("No result found")
                return self._items[0]

            def scalars(self):
                class Scalars:
                    def __init__(self, items):
                        self._items = items
                    def all(self):
                        return self._items
                return Scalars(self._items)

            def all(self):
                if not self._items:
                    return []
                # If wrapped in a tuple (like Cluster + count), return as is
                if isinstance(self._items[0], tuple):
                    return self._items
                return self._items

        # Extremely naive matching based on class
        target_class = getattr(stmt, 'froms', [None])[0]
        if hasattr(target_class, 'name'):
            table_name = target_class.name
            if table_name == 'content_items':
                return Result(self._data.get('items', []))
            elif table_name == 'clusters':
                # Return tuples for cluster list endpoint
                return Result([(c, 5) for c in self._data.get('clusters', [])])
            elif table_name == 'sources':
                return Result(self._data.get('sources', []))
            elif table_name == 'item_links':
                return Result([])
            elif table_name == 'trending_briefs':
                return Result([self._data.get('brief', None)])
            elif table_name == 'content_scores':
                return Result(self._data.get('scores', []))
        
        # Fallback for count queries etc
        return Result([len(self._data.get('items', []))])

    def commit(self):
        pass

    def refresh(self, obj):
        pass

    def close(self):
        pass


@pytest.fixture
def mock_db():
    source_id = uuid4()
    cluster_id = uuid4()
    item_id = uuid4()

    source = Source(
        id=source_id,
        name="Test Source",
        url="https://test.com",
        type=SourceType.RSS,
        category=SourceCategory.BLOG,
        added_by="system",
        is_active=True,
    )

    cluster = Cluster(
        id=cluster_id,
        label="Test Cluster",
        summary="A test cluster",
        is_active=True,
    )

    item = ContentItem(
        id=item_id,
        title="Test Item",
        url="https://test.com/item1",
        published_at=datetime.now(timezone.utc),
        category=ContentCategory.COMPANY_BLOG,
        score=0.95,
        is_trending=True,
        summary_status=SummaryStatus.COMPLETE,
        source_id=source_id,
        cluster_id=cluster_id,
    )
    # Wire relationships for the mapper
    item.source = source
    item.cluster = cluster
    
    score = ContentScore(
        item_id=item_id,
        composite_score=0.95,
        citation_score=0.9,
        engagement_score=0.8,
        sentiment_score=0.7,
        recency_score=0.9,
        authority_score=0.8,
        score_version=1,
        computed_at=datetime.now(timezone.utc)
    )

    mock_data = {
        'items': [item],
        'sources': [source],
        'clusters': [cluster],
        'scores': [score],
        'brief': None,
    }

    session = MockSession(mock_data)
    
    # Override dependencies
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis] = lambda: MockRedis()
    
    yield session
    
    # Clean up
    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_feed_endpoint(mock_db):
    response = client.get("/api/v1/feed?sort=score&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Test Item"
    assert data["items"][0]["source"]["name"] == "Test Source"
    assert data["items"][0]["cluster"]["label"] == "Test Cluster"


def test_trending_endpoint(mock_db):
    response = client.get("/api/v1/trending")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["is_trending"] is True


def test_clusters_endpoint(mock_db):
    response = client.get("/api/v1/clusters")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["label"] == "Test Cluster"


def test_sources_endpoint(mock_db):
    response = client.get("/api/v1/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Source"


def test_item_detail(mock_db):
    # Get the ID from the mock DB items
    item_id = str(mock_db._data['items'][0].id)
    response = client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Item"
    assert data["score"] == 0.95


def test_item_score_breakdown(mock_db):
    item_id = str(mock_db._data['items'][0].id)
    
    # We need to mock _get_weights in athena.pipeline.scoring for this test
    # since it does a separate DB query
    from unittest.mock import patch
    with patch("athena.pipeline.scoring._get_weights", return_value={"citation": 0.3, "engagement": 0.15, "sentiment": 0.15, "recency": 0.2, "authority": 0.2}):
        response = client.get(f"/api/v1/items/{item_id}/score-breakdown")
        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == item_id
        assert data["composite_score"] == 0.95
        assert "citation_impact" in data["signals"]
