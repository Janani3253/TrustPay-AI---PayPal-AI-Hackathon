"""Comprehensive tests for Order Creation and Customer Approval lifecycle (Phase 8)."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import connect, initialize_database
from app.main import app
from app.schemas.product import NormalizedProduct
from app.services.cart_service import cart_service

MOCK_USER = {
    "id": 980,
    "email": "order_user@example.com",
    "name": "Order User",
    "role": "user",
}


@pytest.fixture(autouse=True)
def setup_db():
    initialize_database()
    with connect() as conn:
        conn.execute("DELETE FROM approvals")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM cart_items")
        conn.execute("DELETE FROM users WHERE email = 'order_user@example.com'")
        conn.execute(
            """INSERT INTO users (id, name, email, password_hash, created_at)
               VALUES (980, 'Order User', 'order_user@example.com', 'dummyhash', '2026-11-04T00:00:00Z')"""
        )


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_order_creation_empty_cart_fails(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=980)

    response = await auth_client.post(
        "/api/orders",
        json={"intent": {"prompt": "Buy a laptop", "budget": 1000, "currency": "USD"}},
    )
    assert response.status_code == 400
    assert "empty cart" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_order_creation_success_with_snapshot(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=980)

    mock_product = NormalizedProduct(
        id=1,
        title="Clean Developer Laptop",
        price=Decimal("899.99"),
        brand="Apple",
        description="High performance 16GB RAM laptop",
        category="laptops",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product

        # 1. Add item to cart
        add_res = await auth_client.post(
            "/api/cart/items",
            json={"product_id": 1, "quantity": 1},
        )
        assert add_res.status_code == 200

        # 2. Create order
        order_res = await auth_client.post(
            "/api/orders",
            json={
                "intent": {
                    "prompt": "Buy a laptop under 1000",
                    "budget": 1000.0,
                    "currency": "USD",
                    "required_specifications": {"ram": "16GB"},
                }
            },
        )
        assert order_res.status_code == 201
        order_data = order_res.json()
        assert order_data["id"] is not None
        assert order_data["version"] == 1
        assert order_data["status"] == "pending_verification"
        assert len(order_data["items"]) == 1
        assert order_data["totals"]["subtotal"] == 899.99

        # 3. Retrieve order
        get_res = await auth_client.get(f"/api/orders/{order_data['id']}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == order_data["id"]


@pytest.mark.asyncio
async def test_approval_unverified_order_rejected(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=980)

    mock_product = NormalizedProduct(
        id=1,
        title="Clean Developer Laptop",
        price=Decimal("899.99"),
        brand="Apple",
        description="16GB RAM laptop",
        category="laptops",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product
        await auth_client.post("/api/cart/items", json={"product_id": 1, "quantity": 1})

        order_res = await auth_client.post(
            "/api/orders",
            json={"intent": {"budget": 1000.0, "currency": "USD"}},
        )
        order_id = order_res.json()["id"]

        # Attempt approval prior to IntentLock verification
        appr_res = await auth_client.post(
            f"/api/approvals/{order_id}/approve",
            json={"order_version": 1},
        )
        assert appr_res.status_code == 409
        assert "must pass backend verification" in appr_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_order_full_verification_approval_workflow(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=980)

    mock_product = NormalizedProduct(
        id=1,
        title="Apple MacBook Pro 16GB RAM 512GB SSD",
        price=Decimal("899.99"),
        brand="Apple",
        description="Apple laptop with 16GB RAM and 512GB SSD storage",
        category="laptops",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = mock_product

        # Add item
        await auth_client.post("/api/cart/items", json={"product_id": 1, "quantity": 1})

        # Create Order
        order_res = await auth_client.post(
            "/api/orders",
            json={
                "intent": {
                    "prompt": "Need an Apple laptop with 16GB RAM under $1000",
                    "maximumBudget": 1000.0,
                    "currency": "USD",
                    "structured_intent": {
                        "budget": {"amount": 1000.0, "currency": "USD"},
                        "mandatory_specifications": [
                            {"name": "RAM", "operator": "GTE", "value": "16GB"},
                            {"name": "Brand", "operator": "EQ", "value": "Apple"},
                        ],
                    },
                }
            },
        )
        order_id = order_res.json()["id"]

        # IntentLock Verification
        verify_res = await auth_client.post(
            "/api/verification/order",
            json={"order_id": order_id},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["status"] == "Passed"

        # Customer Approval
        appr_res = await auth_client.post(
            f"/api/approvals/{order_id}/approve",
            json={"order_version": 1},
        )
        assert appr_res.status_code == 200
        assert appr_res.json()["status"] == "approved"
        assert appr_res.json()["order_id"] == order_id

        # Idempotent re-approval
        reappr_res = await auth_client.post(
            f"/api/approvals/{order_id}/approve",
            json={"order_version": 1},
        )
        assert reappr_res.status_code == 200
        assert reappr_res.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_approval_stale_cart_rejected(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=980)

    p1 = NormalizedProduct(
        id=1,
        title="Laptop 1",
        price=Decimal("100.00"),
        brand="Apple",
        description="Clean laptop",
        category="laptops",
        platform_id="dummyjson",
    )
    p2 = NormalizedProduct(
        id=2,
        title="Laptop 2",
        price=Decimal("200.00"),
        brand="Apple",
        description="Clean laptop 2",
        category="laptops",
        platform_id="dummyjson",
    )

    async def mock_get_details(product_id, **kwargs):
        return p1 if product_id == 1 else p2

    with patch("app.services.cart_service.product_service.get_product_details", side_effect=mock_get_details):
        await auth_client.post("/api/cart/items", json={"product_id": 1, "quantity": 1})

        order_res = await auth_client.post(
            "/api/orders",
            json={"intent": {"maximumBudget": 500.0, "currency": "USD"}},
        )
        order_id = order_res.json()["id"]

        # Verify
        verify_res = await auth_client.post(
            "/api/verification/order",
            json={"order_id": order_id},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["status"] == "Passed"

        # Mutate cart behind the scenes (add another product)
        await auth_client.post("/api/cart/items", json={"product_id": 2, "quantity": 1})

        # Attempt approval -> must detect cart mutation and reject with 409
        appr_res = await auth_client.post(
            f"/api/approvals/{order_id}/approve",
            json={"order_version": 1},
        )
        assert appr_res.status_code == 409
        assert "order changed" in appr_res.json()["detail"].lower()
