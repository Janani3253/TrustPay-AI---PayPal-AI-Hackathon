"""Service layer for Order lifecycle management."""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.services.cart_service import cart_service
from app.core.audit import add_audit


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def calculate_snapshot_hash(items: List[Dict[str, Any]], totals: Dict[str, Any], intent: Dict[str, Any], cart_version: int) -> str:
    """Compute deterministic SHA-256 hash of immutable order snapshot components."""
    normalized_items = [
        {"product_id": item["product"]["id"], "quantity": item["quantity"], "price": float(item["product"].get("price", 0))}
        for item in sorted(items, key=lambda x: x["product"]["id"])
    ]
    raw_payload = json_dump({
        "items": normalized_items,
        "totals": {
            "subtotal": float(totals.get("subtotal", 0)),
            "shipping": float(totals.get("shipping", 0)),
            "tax": float(totals.get("tax", 0)),
            "total": float(totals.get("total", 0)),
            "currency": totals.get("currency", "USD"),
        },
        "intent": intent,
        "cart_version": cart_version,
    })
    return hashlib.sha256(raw_payload.encode()).hexdigest()


def order_matches_cart(order_items: List[Dict[str, Any]], current_cart_items: List[Dict[str, Any]]) -> bool:
    """Verify if the order items exactly match the current cart items in products and quantities."""
    if len(order_items) != len(current_cart_items):
        return False

    order_map = {item["product"]["id"]: item["quantity"] for item in order_items}
    cart_map = {item["product"]["id"]: item["quantity"] for item in current_cart_items}
    return order_map == cart_map


class OrderService:
    """Orchestrates order creation, validation, and snapshotting."""

    @staticmethod
    async def create_order(
        user_id: int,
        intent: Dict[str, Any],
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Create a verified/draft order from the current shopping cart."""
        cart_data = await cart_service.get_cart(user_id)
        items = cart_data.get("items", [])
        totals = cart_data.get("totals", {})
        cart_version = cart_data.get("version", 1)

        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create an order from an empty cart.",
            )

        order_id = str(uuid.uuid4())
        snapshot_hash = calculate_snapshot_hash(items, totals, intent, cart_version)
        now = utc_now()

        order = Order(
            id=order_id,
            user_id=user_id,
            version=cart_version,
            status="pending_verification",
            intent_json=intent,
            items_json=items,
            subtotal=totals.get("subtotal", 0.0),
            shipping=totals.get("shipping", 0.0),
            tax=totals.get("tax", 0.0),
            total=totals.get("total", 0.0),
            currency=totals.get("currency", "USD"),
            snapshot_hash=snapshot_hash,
            checks_json=None,
            paypal_order_id=None,
            created_at=now,
            updated_at=now,
        )

        await OrderRepository.create_order(session, order)
        add_audit(user_id, "Order created", f"Created order {order_id} version {cart_version}.")

        return {
            "id": order_id,
            "version": cart_version,
            "status": "pending_verification",
            "items": items,
            "intent": intent,
            "totals": totals,
            "created_at": now.isoformat(),
        }

    @staticmethod
    async def get_order(
        order_id: str,
        user_id: int,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Retrieve order details verifying user ownership."""
        order = await OrderRepository.get_by_id_and_user_id(session, order_id, user_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order was not found.",
            )

        return {
            "id": order.id,
            "version": order.version,
            "status": order.status,
            "items": order.items_json if isinstance(order.items_json, list) else json.loads(order.items_json),
            "intent": order.intent_json if isinstance(order.intent_json, dict) else json.loads(order.intent_json),
            "totals": {
                "subtotal": float(order.subtotal),
                "shipping": float(order.shipping),
                "tax": float(order.tax),
                "total": float(order.total),
                "currency": order.currency,
            },
            "created_at": order.created_at.isoformat() if isinstance(order.created_at, datetime) else str(order.created_at),
            "checks": order.checks_json if isinstance(order.checks_json, dict) else (json.loads(order.checks_json) if order.checks_json else None),
            "paypal_order_id": order.paypal_order_id,
        }
