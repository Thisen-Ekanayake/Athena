import pytest
from httpx import AsyncClient, ASGITransport
from athena.api.main import app

@pytest.mark.skip(reason="Requires test DB setup")
@pytest.mark.asyncio
async def test_admin_qa_sessions_endpoint():
    # Simple check that endpoint exists and returns 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/qa/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "daily_spend_usd" in data
        assert "questions_today" in data
        assert "recent_sessions" in data

@pytest.mark.skip(reason="Stub")
@pytest.mark.asyncio
async def test_qa_adversarial_out_of_context():
    pass

@pytest.mark.skip(reason="Stub")
@pytest.mark.asyncio
async def test_qa_e2e_flow():
    pass
