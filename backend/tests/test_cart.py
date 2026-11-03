from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.main import app
from app.schemas.product import NormalizedProduct
from app.services.cart_service import cart_service

MOCK_USER = {"id": 1, "name": "Cart Shopper", "email": "cart@trustpay.ai"}


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client():
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client


@pytest.mark.asyncio
async def test_cart_unauthenticated_rejected(unauth_client: AsyncClient):
    resp = await unauth_client.get("/api/cart")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_empty_cart(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=1)
    resp = await auth_client.get("/api/cart")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "totals" in data
    assert data["totals"]["total"] == 0.0
    assert data["totals"]["currency"] == "USD"


@pytest.mark.asyncio
async def test_add_item_trusted_product(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=1)

    mock_product = NormalizedProduct(
        id=15,
        title="Ergonomic Mouse",
        description="Wireless mouse with silent click.",
        price=Decimal("40.00"),
        category="electronics",
        brand="LogiTech",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product

        resp = await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["product"]["id"] == 15
        assert item["quantity"] == 1
        assert "content_hash" in item
        assert item["security_risk"] == "SAFE"

        # Totals check: subtotal 40.0, shipping 9.99, tax 2.00 (5%), total 51.99
        totals = data["totals"]
        assert totals["subtotal"] == 40.0
        assert totals["shipping"] == 9.99
        assert totals["tax"] == 2.0
        assert totals["total"] == 51.99


@pytest.mark.asyncio
async def test_add_item_quantity_increment(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=1)

    mock_product = NormalizedProduct(
        id=15,
        title="Ergonomic Mouse",
        description="Wireless mouse.",
        price=Decimal("40.00"),
        category="electronics",
        brand="LogiTech",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product

        # Add 1
        await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 1})
        # Add 2 more
        resp = await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["quantity"] == 3


@pytest.mark.asyncio
async def test_update_item_quantity(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=1)

    mock_product = NormalizedProduct(
        id=15,
        title="Ergonomic Mouse",
        description="Wireless mouse.",
        price=Decimal("40.00"),
        category="electronics",
        brand="LogiTech",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product
        await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 1})

    resp = await auth_client.put("/api/cart/items/15", json={"quantity": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"][0]["quantity"] == 5


@pytest.mark.asyncio
async def test_delete_item_and_clear_cart(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=1)

    mock_product = NormalizedProduct(
        id=15,
        title="Ergonomic Mouse",
        description="Wireless mouse.",
        price=Decimal("40.00"),
        category="electronics",
        brand="LogiTech",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product
        await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 1})

    # Delete single item
    resp_del = await auth_client.delete("/api/cart/items/15")
    assert resp_del.status_code == 204

    cart_after = await auth_client.get("/api/cart")
    assert len(cart_after.json()["items"]) == 0

    # Add again and clear all
    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product
        await auth_client.post("/api/cart/items", json={"product_id": 15, "quantity": 2})

    resp_clear = await auth_client.delete("/api/cart/items")
    assert resp_clear.status_code == 204

    cart_cleared = await auth_client.get("/api/cart")
    assert len(cart_cleared.json()["items"]) == 0

