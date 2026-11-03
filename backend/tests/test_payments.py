"""Comprehensive tests for PayPal Sandbox Payment Integration (Phase 9)."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import connect, initialize_database
from app.main import app
from app.schemas.product import NormalizedProduct
from app.services.cart_service import cart_service
from app.services.paypal_service import paypal_service

MOCK_USER = {
    "id": 990,
    "email": "payment_user@example.com",
    "name": "Payment User",
    "role": "user",
}


@pytest.fixture(autouse=True)
def setup_db():
    initialize_database()
    with connect() as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM approvals")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM cart_items")
        conn.execute("DELETE FROM users WHERE email = 'payment_user@example.com'")
        conn.execute(
            """INSERT INTO users (id, name, email, password_hash, created_at)
               VALUES (990, 'Payment User', 'payment_user@example.com', 'dummyhash', '2026-11-04T00:00:00Z')"""
        )


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
async def test_payments_unauthenticated_rejected(unauth_client: AsyncClient):
    res1 = await unauth_client.post("/api/payments/create-order", json={"order_id": "none"})
    assert res1.status_code == 401

    res2 = await unauth_client.post("/api/payments/capture-order", json={"paypal_order_id": "none"})
    assert res2.status_code == 401


@pytest.mark.asyncio
async def test_payment_creation_unapproved_order_rejected(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=990)

    p = NormalizedProduct(
        id=1,
        title="Laptop",
        price=Decimal("500.00"),
        brand="Dell",
        description="Clean laptop",
        category="laptops",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = p
        await auth_client.post("/api/cart/items", json={"product_id": 1, "quantity": 1})

        order_res = await auth_client.post(
            "/api/orders",
            json={"intent": {"maximumBudget": 600.0, "currency": "USD"}},
        )
        order_id = order_res.json()["id"]

        # Attempt to create payment before customer approval
        pay_res = await auth_client.post(
            "/api/payments/create-order",
            json={"order_id": order_id},
        )
        assert pay_res.status_code == 409
        assert "must pass before payment" in pay_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_payment_create_and_capture_full_workflow(auth_client: AsyncClient):
    await cart_service.clear_cart(user_id=990)

    p = NormalizedProduct(
        id=1,
        title="Apple MacBook Pro 16GB RAM 512GB SSD",
        price=Decimal("950.00"),
        brand="Apple",
        description="Apple laptop with 16GB RAM",
        category="laptops",
        platform_id="dummyjson",
    )

    with patch("app.services.cart_service.product_service.get_product_details", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = p
        # 1. Add to cart
        await auth_client.post("/api/cart/items", json={"product_id": 1, "quantity": 1})

        # 2. Create order
        order_res = await auth_client.post(
            "/api/orders",
            json={
                "intent": {
                    "prompt": "Need an Apple laptop with 16GB RAM under $1100",
                    "maximumBudget": 1100.0,
                    "currency": "USD",
                    "structured_intent": {
                        "budget": {"amount": 1100.0, "currency": "USD"},
                        "mandatory_specifications": [
                            {"name": "RAM", "operator": "GTE", "value": "16GB"},
                        ],
                    },
                }
            },
        )
        order_id = order_res.json()["id"]

        # 3. Verify
        verify_res = await auth_client.post("/api/verification/order", json={"order_id": order_id})
        assert verify_res.status_code == 200
        assert verify_res.json()["status"] == "Passed"

        # 4. Approve
        appr_res = await auth_client.post(f"/api/approvals/{order_id}/approve", json={"order_version": 1})
        assert appr_res.status_code == 200

        # 5. Create Payment Order (Sandbox)
        pay_res = await auth_client.post("/api/payments/create-order", json={"order_id": order_id})
        assert pay_res.status_code == 200
        pay_data = pay_res.json()
        assert pay_data["order_id"] == order_id
        assert pay_data["paypal_order_id"].startswith("PAYPAL-")
        assert "approval_url" in pay_data
        assert pay_data["status"] == "PENDING"

        # 6. Capture Payment Order
        cap_res = await auth_client.post(
            "/api/payments/capture-order",
            json={"paypal_order_id": pay_data["paypal_order_id"]},
        )
        assert cap_res.status_code == 200
        cap_data = cap_res.json()
        assert cap_data["status"] == "COMPLETED"
        assert cap_data["method"] == "PayPal Sandbox"
        assert cap_data["order_id"] == order_id
        assert cap_data["id"] is not None
        assert cap_data["id"].startswith("TRX-")

        # 7. Cart should now be empty after successful purchase
        cart_res = await auth_client.get("/api/cart")
        assert len(cart_res.json()["items"]) == 0

        # 8. Duplicate capture attempt should be rejected with 409
        dup_res = await auth_client.post(
            "/api/payments/capture-order",
            json={"paypal_order_id": pay_data["paypal_order_id"]},
        )
        assert dup_res.status_code == 409
        assert "already been captured" in dup_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_payment_oauth_token_caching():
    # Test token caching mechanism directly on PayPalService
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"access_token": "mock-cached-access-token", "expires_in": 3600}
        mock_post.return_value = mock_response

        # Temporarily enable paypal configuration for this unit test
        with patch.object(paypal_service, "_cached_token", None):
            with patch.object(paypal_service, "_token_expires_at", 0.0):
                with patch("app.core.config.settings.PAYPAL_CLIENT_ID", "test-client-id"):
                    with patch("app.core.config.settings.PAYPAL_CLIENT_SECRET", "test-client-secret"):
                        token1 = await paypal_service.get_access_token()
                        token2 = await paypal_service.get_access_token()

                        assert token1 == "mock-cached-access-token"
                        assert token2 == "mock-cached-access-token"
                        # Only 1 HTTP call made due to caching!
                        assert mock_post.call_count == 1
