import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import connect
from app.main import app
from app.schemas.verification import BackendVerification, OverallDecision
from app.services.intentlock_engine import IntentLockEngine, intentlock_engine

MOCK_USER = {"id": 1, "name": "IntentLock Tester", "email": "intentlock@trustpay.ai"}


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


def test_intentlock_exact_match_passes():
    intent = {
        "request": "Need ASUS laptop with 16GB RAM and 512GB SSD under $1000",
        "maximumBudget": 1000.0,
        "currency": "USD",
        "structured_intent": {
            "budget": {"amount": 1000.0, "currency": "USD"},
            "mandatory_specifications": [
                {"name": "RAM", "operator": "GTE", "value": "16GB"},
                {"name": "Storage", "operator": "GTE", "value": "512GB"},
                {"name": "Brand", "operator": "EQ", "value": "ASUS"},
            ],
            "excluded_conditions": [],
        },
    }

    cart_items = [
        {
            "product": {
                "id": 1,
                "title": "ASUS ROG Gaming Laptop 16GB RAM 512GB SSD",
                "brand": "ASUS",
                "category": "laptops",
                "price": 850.0,
                "currency": "USD",
                "description": "High performance laptop with 16GB RAM and 512GB SSD.",
            },
            "quantity": 1,
            "security_risk": "SAFE",
        }
    ]

    res = intentlock_engine.verify_order_against_intent(
        order_id="ORD-001",
        order_version=1,
        cart_items=cart_items,
        intent=intent,
        cart_version=1,
    )

    assert res.status == "Passed"
    assert res.decision == OverallDecision.READY_FOR_APPROVAL
    assert all(c.status == "Passed" for c in res.checks)


def test_intentlock_budget_exceeded_fails():
    intent = {
        "maximumBudget": 500.0,
        "currency": "USD",
        "structured_intent": {"budget": {"amount": 500.0, "currency": "USD"}},
    }

    cart_items = [
        {
            "product": {
                "id": 2,
                "title": "Expensive Smartphone",
                "price": 600.0,
                "currency": "USD",
            },
            "quantity": 1,
            "security_risk": "SAFE",
        }
    ]

    res = intentlock_engine.verify_order_against_intent(
        order_id="ORD-002",
        order_version=1,
        cart_items=cart_items,
        intent=intent,
        cart_version=1,
    )

    assert res.status == "Failed"
    assert res.decision == OverallDecision.BLOCKED
    budget_check = next(c for c in res.checks if "Budget" in c.name)
    assert budget_check.status == "Failed"
    assert budget_check.critical is True


def test_intentlock_mandatory_spec_mismatch_fails():
    intent = {
        "maximumBudget": 1000.0,
        "currency": "USD",
        "structured_intent": {
            "mandatory_specifications": [
                {"name": "RAM", "operator": "GTE", "value": "16GB"},
            ],
        },
    }

    # Product only has 8GB RAM
    cart_items = [
        {
            "product": {
                "id": 3,
                "title": "Entry Laptop 8GB RAM",
                "price": 400.0,
                "currency": "USD",
                "description": "Basic laptop with 8GB RAM.",
            },
            "quantity": 1,
            "security_risk": "SAFE",
        }
    ]

    res = intentlock_engine.verify_order_against_intent(
        order_id="ORD-003",
        order_version=1,
        cart_items=cart_items,
        intent=intent,
        cart_version=1,
    )

    assert res.status == "Failed"
    assert res.decision == OverallDecision.BLOCKED
    ram_check = next(c for c in res.checks if c.name == "Specification: RAM")
    assert ram_check.status == "Failed"


def test_intentlock_exclusion_violated_fails():
    intent = {
        "maximumBudget": 1000.0,
        "currency": "USD",
        "structured_intent": {
            "excluded_conditions": [{"condition": "refurbished"}],
        },
    }

    cart_items = [
        {
            "product": {
                "id": 4,
                "title": "Refurbished Premium Tablet",
                "price": 300.0,
                "currency": "USD",
                "description": "Certified refurbished tablet.",
            },
            "quantity": 1,
            "security_risk": "SAFE",
        }
    ]

    res = intentlock_engine.verify_order_against_intent(
        order_id="ORD-004",
        order_version=1,
        cart_items=cart_items,
        intent=intent,
        cart_version=1,
    )

    assert res.status == "Failed"
    assert res.decision == OverallDecision.BLOCKED
    excl_check = next(c for c in res.checks if c.name.startswith("Exclusions:"))
    assert excl_check.status == "Failed"


def test_intentlock_malicious_security_blocks():
    intent = {"maximumBudget": 1000.0, "currency": "USD"}

    cart_items = [
        {
            "product": {
                "id": 5,
                "title": "Exploit Gadget",
                "price": 20.0,
                "currency": "USD",
            },
            "quantity": 1,
            "security_risk": "MALICIOUS",
        }
    ]

    res = intentlock_engine.verify_order_against_intent(
        order_id="ORD-005",
        order_version=1,
        cart_items=cart_items,
        intent=intent,
        cart_version=1,
    )

    assert res.status == "Failed"
    assert res.decision == OverallDecision.BLOCKED
    sec_check = next(c for c in res.checks if "Security Policy" in c.name)
    assert sec_check.status == "Failed"
    assert sec_check.critical is True


@pytest.mark.asyncio
async def test_api_verification_order_flow(auth_client: AsyncClient):
    order_id = str(uuid.uuid4())
    intent_data = {
        "request": "Laptop under $1000",
        "maximumBudget": 1000.0,
        "currency": "USD",
        "structured_intent": {
            "budget": {"amount": 1000.0, "currency": "USD"},
            "mandatory_specifications": [],
            "excluded_conditions": [],
        },
    }

    # Insert test order in database
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, email, password_hash, created_at) VALUES (1, 'Test User', 'test@example.com', 'dummy', '2026-01-01')"
        )
        conn.execute(
            """INSERT INTO orders (id, user_id, version, intent_json, cart_json, total, currency, status, created_at, updated_at)
               VALUES (?, 1, 1, ?, '[]', 500.0, 'USD', 'pending_verification', '2026-01-01', '2026-01-01')""",
            (order_id, json.dumps(intent_data)),
        )

    # Mock cart items
    with patch("app.routers.verification.cart_service.get_cart", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = {
            "cart_id": 1,
            "version": 1,
            "items": [
                {
                    "product": {"id": 10, "title": "Verified Laptop", "price": 400.0, "currency": "USD"},
                    "quantity": 1,
                    "security_risk": "SAFE",
                }
            ],
            "totals": {"subtotal": 400.0, "shipping": 9.99, "tax": 20.0, "total": 429.99, "currency": "USD"},
        }

        resp = await auth_client.post("/api/verification/order", json={"order_id": order_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == order_id
        assert data["status"] == "Passed"
        assert len(data["checks"]) >= 2
