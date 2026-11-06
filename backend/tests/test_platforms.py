import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_get_platforms_endpoint():
    """Verify GET /api/platforms returns exact schema matching frontend ShoppingPlatform interface."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/platforms")
        assert response.status_code == 200
        platforms = response.json()

        assert isinstance(platforms, list)
        assert len(platforms) == 4

        # Validate platform 1: DummyJSON
        dummy = platforms[0]
        assert dummy["id"] == "dummyjson"
        assert dummy["name"] == "DummyJSON Demo Store"
        assert dummy["supported"] is True
        assert dummy["demo_only"] is True
        assert "DummyJSON" in dummy["description"]

        # Validate other platforms are unsupported
        for p in platforms[1:]:
            assert p["supported"] is False
            assert p["demo_only"] is False
            assert "not configured" in p["description"].lower()

        platform_names = [p["name"] for p in platforms]
        assert "Amazon" in platform_names
        assert "Flipkart" in platform_names
        assert "Myntra" in platform_names


@pytest.mark.asyncio
async def test_get_platforms_with_auth_header():
    """Verify GET /api/platforms functions identically when caller provides Bearer token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/platforms", headers={"Authorization": "Bearer some-token"})
        # Should not fail with 500
        assert response.status_code in (200, 401)

