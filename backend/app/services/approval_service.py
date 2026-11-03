"""Service layer for Customer IntentLock approval workflow."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.repositories.order_repository import OrderRepository
from app.services.cart_service import cart_service
from app.services.order_service import order_matches_cart, calculate_snapshot_hash
from app.core.audit import add_audit


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    """Manages secure customer approvals for verified orders."""

    @staticmethod
    async def approve_order(
        order_id: str,
        order_version: int,
        user_id: int,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Verify conditions and record customer approval for an order."""
        order = await OrderRepository.get_by_id_and_user_id(session, order_id, user_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order was not found.",
            )

        # Idempotent response: If already approved at the same version
        if order.status == "approved" and order.version == order_version:
            return {
                "order_id": order_id,
                "order_version": order_version,
                "status": "approved",
            }

        # Check order version
        if order.version != order_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order changed after verification. Recreate and verify it before approval.",
            )

        # Current cart check: ensure cart hasn't changed since order was created
        cart_data = await cart_service.get_cart(user_id)
        current_items = cart_data.get("items", [])
        order_items = order.items_json if isinstance(order.items_json, list) else json.loads(order.items_json)

        if not order_matches_cart(order_items, current_items):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order changed after verification. Recreate and verify it before approval.",
            )

        # Check verification status
        if order.status != "verified":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order must pass backend verification before approval.",
            )

        # Ensure verification checks actually passed
        checks = order.checks_json if isinstance(order.checks_json, dict) else (json.loads(order.checks_json) if order.checks_json else {})
        if checks.get("status") != "Passed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order verification checks failed; cannot approve unverified order.",
            )

        # Create approval record
        now = utc_now()
        snapshot_hash = order.snapshot_hash or calculate_snapshot_hash(
            order_items,
            {
                "subtotal": float(order.subtotal),
                "shipping": float(order.shipping),
                "tax": float(order.tax),
                "total": float(order.total),
                "currency": order.currency,
            },
            order.intent_json if isinstance(order.intent_json, dict) else json.loads(order.intent_json),
            order.version,
        )

        approval = Approval(
            id=str(uuid.uuid4()),
            order_id=order_id,
            user_id=user_id,
            approved_version=order_version,
            approved_snapshot_hash=snapshot_hash,
            status="approved",
            approved_at=now,
        )

        # Update order status
        await OrderRepository.update_order(session, order, status="approved")
        await OrderRepository.record_approval(session, approval)

        add_audit(user_id, "Customer approval recorded", f"Customer approved order {order_id} version {order_version}.")

        return {
            "order_id": order_id,
            "order_version": order_version,
            "status": "approved",
        }
