"""FastAPI router for Dashboard metrics."""

from typing import Any, Dict
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.database import connect
from app.schemas.dashboard import DashboardMetricsResponse

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.get("", response_model=DashboardMetricsResponse, summary="Get Dashboard Overview Metrics")
async def get_dashboard(user: Any = Depends(get_current_user)) -> Dict[str, Any]:
    """Retrieve security metrics, transaction counts, and recent activity for the user."""
    user_id = _extract_user_id(user)

    with connect() as connection:
        requests_total = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE user_id = ? AND type = 'Purchase policy created'",
            (user_id,),
        ).fetchone()[0]

        verified_orders = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status IN ('verified', 'approved', 'paypal_pending', 'completed')",
            (user_id,),
        ).fetchone()[0]

        blocked_orders = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'verification_failed'",
            (user_id,),
        ).fetchone()[0]

        transaction_rows = connection.execute(
            "SELECT id, order_id, product, amount, currency, date, method, status, verification, paypal_reference FROM transactions WHERE user_id = ? ORDER BY date DESC, rowid DESC LIMIT 5",
            (user_id,),
        ).fetchall()

        recent_transactions = []
        for r in transaction_rows:
            d = dict(r)
            d["orderId"] = d.get("order_id")
            d["paypalReference"] = d.get("paypal_reference")
            recent_transactions.append(d)

        activity_rows = connection.execute(
            "SELECT type, timestamp, description FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        security_activity = [dict(r) for r in activity_rows]

    return {
        "total_requests": requests_total,
        "verified_orders": verified_orders,
        "blocked_transactions": blocked_orders,
        "recent_transactions": recent_transactions,
        "security_activity": security_activity,
    }

