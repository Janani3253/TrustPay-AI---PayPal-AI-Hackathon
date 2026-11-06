"""Repository for Transactions persistence and querying."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.transaction import Transaction
from app.database import connect


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TransactionRepository:
    """Manages transaction records across PostgreSQL and SQLite."""

    @staticmethod
    async def create(
        transaction_id: str,
        user_id: int,
        order_id: str,
        product: str,
        amount: float,
        currency: str,
        date: str,
        method: str = "PayPal Sandbox",
        status: str = "Completed",
        verification: str = "Backend verified",
        paypal_reference: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Persist a new transaction."""
        # 1. Dual mirror to SQLite
        try:
            with connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO transactions
                       (id, user_id, order_id, product, amount, currency, date, method, status, verification, paypal_reference)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        transaction_id,
                        user_id,
                        order_id,
                        product,
                        amount,
                        currency,
                        date,
                        method,
                        status,
                        verification,
                        paypal_reference,
                    ),
                )
        except Exception:
            pass

        # 2. Write to PostgreSQL if configured
        trx_obj = Transaction(
            id=transaction_id,
            user_id=user_id,
            order_id=order_id,
            product=product,
            amount=Decimal(str(amount)),
            currency=currency,
            date=date,
            method=method,
            status=status,
            verification=verification,
            paypal_reference=paypal_reference,
            created_at=utc_now(),
        )

        if session is not None:
            session.add(trx_obj)
            await session.flush()
        else:
            factory = get_session_factory()
            if factory is not None:
                try:
                    async with factory() as new_session:
                        new_session.add(trx_obj)
                        await new_session.commit()
                except Exception:
                    pass

        return {
            "id": transaction_id,
            "order_id": order_id,
            "orderId": order_id,
            "product": product,
            "amount": amount,
            "currency": currency,
            "date": date,
            "method": method,
            "status": status,
            "verification": verification,
            "paypal_reference": paypal_reference,
            "paypalReference": paypal_reference,
        }

    @staticmethod
    async def get_user_transactions(user_id: int) -> List[Dict[str, Any]]:
        """Retrieve all transactions for a user ordered by date DESC."""
        factory = get_session_factory()
        if factory is not None:
            try:
                async with factory() as session:
                    stmt = (
                        select(Transaction)
                        .where(Transaction.user_id == user_id)
                        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
                    )
                    result = await session.execute(stmt)
                    rows = result.scalars().all()
                    if rows:
                        return [
                            {
                                "id": r.id,
                                "order_id": r.order_id,
                                "orderId": r.order_id,
                                "product": r.product,
                                "amount": float(r.amount),
                                "currency": r.currency,
                                "date": r.date,
                                "method": r.method,
                                "status": r.status,
                                "verification": r.verification,
                                "paypal_reference": r.paypal_reference,
                                "paypalReference": r.paypal_reference,
                            }
                            for r in rows
                        ]
            except Exception:
                pass

        # Fallback to SQLite
        try:
            with connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC, rowid DESC",
                    (user_id,),
                ).fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["orderId"] = d.get("order_id")
                    d["paypalReference"] = d.get("paypal_reference")
                    result.append(d)
                return result
        except Exception:
            return []

