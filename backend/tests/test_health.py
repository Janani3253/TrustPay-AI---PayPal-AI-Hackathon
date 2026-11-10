import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_health_endpoint(async_client: AsyncClient):
    """Verify GET /health returns application liveness status ok."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["application"] == "TrustPay AI"
    assert "environment" in data


@pytest.mark.asyncio
async def test_readiness_health_not_configured(async_client: AsyncClient):
    """Verify GET /api/health reports degraded when PostgreSQL is unconfigured."""
    with patch(
        "app.main.check_db_connectivity",
        AsyncMock(return_value={"status": "not_configured"}),
    ):
        response = await async_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["postgresql"]["status"] == "not_configured"


@pytest.mark.asyncio
async def test_readiness_health_connected(async_client: AsyncClient):
    """Verify GET /api/health reports ok when PostgreSQL is connected."""
    with patch(
        "app.main.check_db_connectivity",
        AsyncMock(return_value={"status": "connected", "version": "16"}),
    ):
        response = await async_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["services"]["postgresql"]["status"] == "connected"
        assert data["services"]["postgresql"]["engine"] == "PostgreSQL"
        assert data["services"]["postgresql"]["version"] == "16"


@pytest.mark.asyncio
async def test_readiness_health_unavailable(async_client: AsyncClient):
    """Verify GET /api/health reports degraded when PostgreSQL connection fails."""
    with patch(
        "app.main.check_db_connectivity",
        AsyncMock(return_value={"status": "unavailable", "message": "Connection error"}),
    ):
        response = await async_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["postgresql"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_health_endpoints_do_not_leak_secrets(async_client: AsyncClient):
    """Verify response payloads never leak passwords or secret keys."""
    for path in ["/health", "/api/health"]:
        response = await async_client.get(path)
        body = response.text.lower()
        for forbidden in ["password", "secret", "private_key", "token_key"]:
            assert forbidden not in body, f"Leaked {forbidden} in {path}"

