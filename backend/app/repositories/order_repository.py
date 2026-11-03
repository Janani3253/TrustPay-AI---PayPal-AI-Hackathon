"""Repository for Orders and Approvals persistence."""

from datetime import datetime, timezone
import json
from typing import Any, Optional
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.order import Order
from app.models.approval import Approval
from app.database import connect


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


class OrderRepository:
    """PostgreSQL and dual-mirror repository for order lifecycle and customer approvals."""

    @staticmethod
    async def create_order(session: Optional[AsyncSession], order: Order) -> Order:
        """Persist order in PostgreSQL (if session given) and dual-mirror to SQLite."""
        if session is not None:
            session.add(order)
            await session.flush()

        # Dual mirror to SQLite for backward-compatibility with existing data
        try:
            with connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO orders
                       (id, user_id, version, intent_json, cart_json, total, currency, status, checks_json, paypal_order_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order.id,
                        order.user_id,
                        order.version,
                        json_dump(order.intent_json),
                        json_dump(order.items_json),
                        float(order.total),
                        order.currency,
                        order.status,
                        json_dump(order.checks_json) if order.checks_json else None,
                        order.paypal_order_id,
                        order.created_at.isoformat() if isinstance(order.created_at, datetime) else str(order.created_at),
                        order.updated_at.isoformat() if isinstance(order.updated_at, datetime) else str(order.updated_at),
                    ),
                )
        except Exception:
            pass

        return order

    @staticmethod
    async def get_by_id_and_user_id(
        session: Optional[AsyncSession], order_id: str, user_id: int
    ) -> Optional[Order]:
        """Fetch order by ID and User ID."""
        if session is not None:
            stmt = select(Order).where(Order.id == order_id, Order.user_id == user_id)
            result = await session.execute(stmt)
            order = result.scalar_one_or_none()
            if order is not None:
                return order

        # Fallback to SQLite mirror
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM orders WHERE id = ? AND user_id = ?",
                    (order_id, user_id),
                ).fetchone()
                if row:
                    order = Order(
                        id=row["id"],
                        user_id=row["user_id"],
                        version=row["version"],
                        status=row["status"],
                        intent_json=json.loads(row["intent_json"]),
                        items_json=json.loads(row["cart_json"]),
                        subtotal=row["total"],
                        shipping=0.0,
                        tax=0.0,
                        total=row["total"],
                        currency=row["currency"],
                        checks_json=json.loads(row["checks_json"]) if row["checks_json"] else None,
                        snapshot_hash="",
                        paypal_order_id=row["paypal_order_id"],
                    )
                    return order
        except Exception:
            pass

        return None

    @staticmethod
    async def get_by_paypal_order_id_and_user_id(
        session: Optional[AsyncSession], paypal_order_id: str, user_id: int
    ) -> Optional[Order]:
        """Fetch order by paypal_order_id and user_id."""
        if session is not None:
            stmt = select(Order).where(Order.paypal_order_id == paypal_order_id, Order.user_id == user_id)
            result = await session.execute(stmt)
            order = result.scalar_one_or_none()
            if order is not None:
                return order

        # Fallback to SQLite mirror
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM orders WHERE paypal_order_id = ? AND user_id = ?",
                    (paypal_order_id, user_id),
                ).fetchone()
                if row:
                    return Order(
                        id=row["id"],
                        user_id=row["user_id"],
                        version=row["version"],
                        status=row["status"],
                        intent_json=json.loads(row["intent_json"]),
                        items_json=json.loads(row["cart_json"]),
                        subtotal=row["total"],
                        shipping=0.0,
                        tax=0.0,
                        total=row["total"],
                        currency=row["currency"],
                        checks_json=json.loads(row["checks_json"]) if row["checks_json"] else None,
                        snapshot_hash="",
                        paypal_order_id=row["paypal_order_id"],
                    )
        except Exception:
            pass

        return None

    @staticmethod
    async def update_order(
        session: Optional[AsyncSession],
        order: Order,
        status: Optional[str] = None,
        checks_json: Optional[dict] = None,
        paypal_order_id: Optional[str] = None,
    ) -> Order:
        """Update order fields in PostgreSQL and SQLite mirror."""
        if status is not None:
            order.status = status
        if checks_json is not None:
            order.checks_json = checks_json
        if paypal_order_id is not None:
            order.paypal_order_id = paypal_order_id
        order.updated_at = utc_now()

        if session is not None:
            session.add(order)
            await session.flush()

        # Mirror to SQLite
        try:
            with connect() as conn:
                conn.execute(
                    """UPDATE orders
                       SET status = ?, checks_json = ?, paypal_order_id = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        order.status,
                        json_dump(order.checks_json) if order.checks_json else None,
                        order.paypal_order_id,
                        order.updated_at.isoformat() if isinstance(order.updated_at, datetime) else str(order.updated_at),
                        order.id,
                    ),
                )
        except Exception:
            pass

        return order

    @staticmethod
    async def record_approval(
        session: Optional[AsyncSession], approval: Approval
    ) -> Approval:
        """Persist approval in PostgreSQL and SQLite."""
        if session is not None:
            session.add(approval)
            await session.flush()

        try:
            with connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO approvals
                       (id, order_id, user_id, approved_version, approved_snapshot_hash, status, approved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        approval.id,
                        approval.order_id,
                        approval.user_id,
                        approval.approved_version,
                        approval.approved_snapshot_hash,
                        approval.status,
                        approval.approved_at.isoformat() if isinstance(approval.approved_at, datetime) else str(approval.approved_at),
                    ),
                )
        except Exception:
            pass

        return approval
