"""Service layer for PayPal REST API Sandbox integration."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
import uuid
import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.audit import add_audit
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.services.cart_service import cart_service
from app.services.order_service import order_matches_cart
from app.database import connect

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PayPalService:
    """Manages PayPal Sandbox OAuth token, order creation, and payment captures."""

    def __init__(self):
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def get_access_token(self) -> str:
        """Retrieve valid OAuth 2.0 access token using client credentials grant."""
        if not settings.is_paypal_configured:
            return "mock-sandbox-token"

        now = asyncio.get_event_loop().time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        async with self._token_lock:
            if self._cached_token and asyncio.get_event_loop().time() < self._token_expires_at:
                return self._cached_token

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{settings.PAYPAL_API_BASE_URL}/v1/oauth2/token",
                        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                        data={"grant_type": "client_credentials"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    self._cached_token = data["access_token"]
                    expires_in = int(data.get("expires_in", 32400))
                    # Buffer 60 seconds
                    self._token_expires_at = asyncio.get_event_loop().time() + max(expires_in - 60, 60)
                    return self._cached_token
            except Exception as exc:
                logger.error("Failed to retrieve PayPal Sandbox access token: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Could not authenticate with PayPal Sandbox API.",
                ) from exc

    async def create_checkout_order(
        self,
        order_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """Create a PayPal Sandbox checkout order for an approved TrustPay order."""
        order = await OrderRepository.get_by_id_and_user_id(None, order_id, user_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order '{order_id}' was not found for this user.",
            )

        if order.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Backend verification and customer approval must pass before payment.",
            )

        # Check cart hasn't mutated since approval
        cart_data = await cart_service.get_cart(user_id)
        current_items = cart_data.get("items", [])
        order_items = order.items_json if isinstance(order.items_json, list) else []

        if not order_matches_cart(order_items, current_items):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approved order is stale; reverify and approve the current cart.",
            )

        # Invariant: Server-calculated amount ONLY
        amount_str = f"{float(order.total):.2f}"
        currency = order.currency or "USD"

        if settings.is_paypal_configured:
            token = await self.get_access_token()
            return_url = f"{settings.FRONTEND_BASE_URL}/payment?order_id={order.id}"
            cancel_url = f"{settings.FRONTEND_BASE_URL}/payment?cancelled=1&order_id={order.id}"

            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{settings.PAYPAL_API_BASE_URL}/v2/checkout/orders",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={
                            "intent": "CAPTURE",
                            "purchase_units": [{
                                "reference_id": order.id,
                                "amount": {"currency_code": currency, "value": amount_str},
                            }],
                            "application_context": {
                                "brand_name": "TrustPay AI Sandbox Demo",
                                "user_action": "PAY_NOW",
                                "return_url": return_url,
                                "cancel_url": cancel_url,
                            },
                        },
                    )
                    resp.raise_for_status()
                    paypal_order = resp.json()
            except httpx.HTTPError as exc:
                logger.error("PayPal Sandbox create order error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal Sandbox could not create the checkout order.",
                ) from exc

            approval_url = next(
                (link["href"] for link in paypal_order.get("links", []) if link.get("rel") == "approve"),
                None,
            )
            if not approval_url:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal Sandbox did not return an approval URL.",
                )
            paypal_order_id = paypal_order["id"]
        else:
            # Deterministic Sandbox Simulation for tests/offline
            paypal_order_id = f"PAYPAL-MOCK-{uuid.uuid4().hex[:10].upper()}"
            approval_url = f"{settings.PAYPAL_API_BASE_URL}/checkoutnow?token={paypal_order_id}"

        # Update order status
        await OrderRepository.update_order(
            None,
            order,
            status="paypal_pending",
            paypal_order_id=paypal_order_id,
        )

        add_audit(user_id, "Sandbox payment initiated", f"Created PayPal Sandbox order for TrustPay order {order.id}.")

        return {
            "order_id": order.id,
            "paypal_order_id": paypal_order_id,
            "approval_url": approval_url,
            "status": "PENDING",
        }

    async def capture_checkout_order(
        self,
        paypal_order_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """Capture payment for a pending PayPal Sandbox order."""
        order = await OrderRepository.get_by_paypal_order_id_and_user_id(None, paypal_order_id, user_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal order is not pending for this account.",
            )

        if order.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment has already been captured for this order.",
            )

        if order.status != "paypal_pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal order is not pending for this account.",
            )

        # Check cart staleness
        cart_data = await cart_service.get_cart(user_id)
        current_items = cart_data.get("items", [])
        order_items = order.items_json if isinstance(order.items_json, list) else []

        if not order_matches_cart(order_items, current_items):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cart changed before payment capture.",
            )

        if settings.is_paypal_configured:
            token = await self.get_access_token()
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{settings.PAYPAL_API_BASE_URL}/v2/checkout/orders/{paypal_order_id}/capture",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={},
                    )
                    resp.raise_for_status()
                    capture_data = resp.json()
            except httpx.HTTPError as exc:
                logger.error("PayPal Sandbox capture error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal Sandbox capture could not be completed.",
                ) from exc

            status_text = capture_data.get("status", "PENDING")
            capture_entries = [
                entry
                for unit in capture_data.get("purchase_units", [])
                for entry in unit.get("payments", {}).get("captures", [])
            ]
            paypal_reference = capture_entries[0].get("id") if capture_entries else paypal_order_id
        else:
            status_text = "COMPLETED"
            paypal_reference = f"CAPTURE-{uuid.uuid4().hex[:10].upper()}"

        transaction_id = f"TRX-{uuid.uuid4().hex[:12].upper()}"
        transaction_date = datetime.now(timezone.utc).date().isoformat()

        if status_text == "COMPLETED":
            product_titles = ", ".join(
                item["product"].get("title", "Product") for item in order_items
            ) or "General Merchandise"

            # Record transaction in SQLite mirror
            try:
                with connect() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO transactions
                           (id, user_id, order_id, product, amount, currency, date, method, status, verification, paypal_reference)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            transaction_id,
                            user_id,
                            order.id,
                            product_titles,
                            float(order.total),
                            order.currency,
                            transaction_date,
                            "PayPal Sandbox",
                            "Completed",
                            "Backend verified",
                            paypal_reference,
                        ),
                    )
            except Exception as exc:
                logger.warning("Failed to record transaction to SQLite: %s", exc)

            # Update order status
            await OrderRepository.update_order(None, order, status="completed")

            # Clear cart
            await cart_service.clear_cart(user_id)

            add_audit(
                user_id,
                "Sandbox payment completed",
                f"PayPal Sandbox capture status: COMPLETED for order {order.id}.",
            )
        else:
            await OrderRepository.update_order(None, order, status=f"paypal_{status_text.lower()}")
            add_audit(
                user_id,
                "Sandbox payment pending",
                f"PayPal Sandbox returned status {status_text} for order {order.id}.",
            )

        return {
            "id": transaction_id if status_text == "COMPLETED" else None,
            "order_id": order.id,
            "paypal_reference": paypal_reference,
            "amount": float(order.total),
            "currency": order.currency,
            "date": transaction_date,
            "status": status_text,
            "method": "PayPal Sandbox",
        }


paypal_service = PayPalService()

