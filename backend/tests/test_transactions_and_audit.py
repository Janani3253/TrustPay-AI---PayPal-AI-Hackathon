"""Comprehensive tests for Transactions, Dashboard, and Tamper-Evident Audit (Phase 10)."""

from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import connect, initialize_database
from app.main import app
from app.repositories.transaction_repository import TransactionRepository
from app.services.audit_service import audit_service

MOCK_USER = {
    "id": 995,
    "email": "audit_user@example.com",
    "name": "Audit User",
    "role": "user",
}


@pytest.fixture(autouse=True)
def setup_db():
    initialize_database()
    with connect() as conn:
        conn.execute("DELETE FROM audit_events WHERE user_id = 995")
        conn.execute("DELETE FROM transactions WHERE user_id = 995")
        conn.execute("DELETE FROM orders WHERE user_id = 995")
        conn.execute("DELETE FROM users WHERE email = 'audit_user@example.com'")
        conn.execute(
            """INSERT INTO users (id, name, email, password_hash, created_at)
               VALUES (995, 'Audit User', 'audit_user@example.com', 'dummyhash', '2026-11-04T00:00:00Z')"""
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
async def test_audit_endpoints_unauthenticated_rejected(unauth_client: AsyncClient):
    assert (await unauth_client.get("/api/transactions")).status_code == 401
    assert (await unauth_client.get("/api/dashboard")).status_code == 401
    assert (await unauth_client.get("/api/audit")).status_code == 401
    assert (await unauth_client.post("/api/audit/verify-integrity")).status_code == 401


@pytest.mark.asyncio
async def test_transaction_management_and_retrieval(auth_client: AsyncClient):
    # Setup dummy order first for foreign key
    with connect() as conn:
        conn.execute(
            """INSERT INTO orders (id, user_id, version, intent_json, cart_json, total, currency, status, created_at, updated_at)
               VALUES ('ORD-TEST-1', 995, 1, '{}', '[]', 250.0, 'USD', 'completed', '2026-11-04T00:00:00Z', '2026-11-04T00:00:00Z')"""
        )

    await TransactionRepository.create(
        transaction_id="TRX-TEST-001",
        user_id=995,
        order_id="ORD-TEST-1",
        product="Gaming Monitor 144Hz",
        amount=250.0,
        currency="USD",
        date="2026-11-04",
        method="PayPal Sandbox",
        status="Completed",
        verification="Backend verified",
        paypal_reference="PAYPAL-REF-999",
    )

    resp = await auth_client.get("/api/transactions")
    assert resp.status_code == 200
    transactions = resp.json()
    assert len(transactions) == 1
    t = transactions[0]
    assert t["id"] == "TRX-TEST-001"
    assert t["product"] == "Gaming Monitor 144Hz"
    assert t["amount"] == 250.0
    assert t["currency"] == "USD"
    assert t["orderId"] == "ORD-TEST-1"
    assert t["paypalReference"] == "PAYPAL-REF-999"


@pytest.mark.asyncio
async def test_dashboard_metrics_aggregation(auth_client: AsyncClient):
    # Record some audit events and orders
    audit_service.record_event(995, "Purchase policy created", "User defined shopping policy.")
    audit_service.record_event(995, "Purchase policy created", "User defined second policy.")

    with connect() as conn:
        conn.execute(
            """INSERT INTO orders (id, user_id, version, intent_json, cart_json, total, currency, status, created_at, updated_at)
               VALUES ('ORD-V1', 995, 1, '{}', '[]', 100.0, 'USD', 'verified', '2026-11-04T00:00:00Z', '2026-11-04T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO orders (id, user_id, version, intent_json, cart_json, total, currency, status, created_at, updated_at)
               VALUES ('ORD-B1', 995, 1, '{}', '[]', 150.0, 'USD', 'verification_failed', '2026-11-04T00:00:00Z', '2026-11-04T00:00:00Z')"""
        )

    resp = await auth_client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_requests"] == 2
    assert data["verified_orders"] == 1
    assert data["blocked_transactions"] == 1
    assert isinstance(data["recent_transactions"], list)
    assert len(data["security_activity"]) >= 2


@pytest.mark.asyncio
async def test_audit_hash_chain_and_cryptographic_verification(auth_client: AsyncClient):
    # 1. Append sequential events
    e1 = audit_service.record_event(995, "Login successful", "Customer logged in from verified IP.")
    assert e1["previousHash"] == "GENESIS"

    e2 = audit_service.record_event(995, "Cart modified", "Added item 15 to cart.")
    assert e2["previousHash"] == e1["hash"]

    e3 = audit_service.record_event(995, "IntentLock verified", "Deterministic rules verified budget.")
    assert e3["previousHash"] == e2["hash"]

    # 2. Retrieve audit list
    trail_res = await auth_client.get("/api/audit")
    assert trail_res.status_code == 200
    events = trail_res.json()
    assert len(events) == 3
    assert events[0]["previousHash"] == "GENESIS"
    assert events[1]["previousHash"] == events[0]["hash"]
    assert events[2]["previousHash"] == events[1]["hash"]

    # 3. Verify integrity: pristine chain should pass
    verify_res = await auth_client.post("/api/audit/verify-integrity")
    assert verify_res.status_code == 200
    assert verify_res.json()["valid"] is True
    assert verify_res.json()["records_checked"] == 3


@pytest.mark.asyncio
async def test_audit_hash_chain_tamper_detection(auth_client: AsyncClient):
    # 1. Create valid chain
    e1 = audit_service.record_event(995, "Step 1", "Initial event")
    e2 = audit_service.record_event(995, "Step 2", "Secondary event")
    e3 = audit_service.record_event(995, "Step 3", "Final event")

    # 2. Tamper with event 2 in the database (malicious attacker alters description)
    with connect() as conn:
        conn.execute(
            "UPDATE audit_events SET description = 'TAMPERED MALICIOUS CONTENT' WHERE id = ?",
            (e2["id"],),
        )

    # 3. Verification must immediately detect the tampering and fail
    verify_res = await auth_client.post("/api/audit/verify-integrity")
    assert verify_res.status_code == 200
    res_data = verify_res.json()
    assert res_data["valid"] is False
    assert res_data["records_checked"] == 3

