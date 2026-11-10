import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.audit import add_audit
from app.core.dependencies import get_current_user
from app.database import connect
from app.models.user import User
from app.schemas import VerifyOrderRequest
from app.schemas.verification import BackendVerification
from app.services.cart_service import cart_service
from app.services.intentlock_engine import intentlock_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/verification", tags=["Verification"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post(
    "/order",
    response_model=BackendVerification,
    status_code=status.HTTP_200_OK,
    summary="Verify purchase against customer intent via IntentLock",
    description="Deterministic verification of budget, specifications, exclusions, security, and cart integrity.",
)
async def verify_order(
    payload: VerifyOrderRequest,
    user: User = Depends(get_current_user),
) -> BackendVerification:
    user_id = _extract_user_id(user)

    # 1. Retrieve order and verify ownership
    with connect() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (payload.order_id, user_id),
        ).fetchone()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{payload.order_id}' was not found for this user.",
        )

    order_version = int(order["version"])
    intent = json.loads(order["intent_json"])

    # 2. Retrieve current cart
    cart_data = await cart_service.get_cart(user_id)
    cart_items = cart_data.get("items", [])
    cart_version = cart_data.get("version", 1)

    # 3. Execute IntentLock Verification Engine
    verification_res = intentlock_engine.verify_order_against_intent(
        order_id=payload.order_id,
        order_version=order_version,
        cart_items=cart_items,
        intent=intent,
        cart_version=cart_version,
    )

    # 4. Update order status and checks in database
    new_status = "verified" if verification_res.status == "Passed" else "verification_failed"
    checks_dict = {
        "status": verification_res.status,
        "decision": verification_res.decision,
        "checks": [c.model_dump() for c in verification_res.checks],
    }
    checks_json = json.dumps(checks_dict)

    with connect() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, checks_json = ? WHERE id = ?",
            (new_status, checks_json, payload.order_id),
        )

    # 5. Audit event
    add_audit(
        user_id=user_id,
        event_type="INTENTLOCK_VERIFICATION_COMPLETED",
        description=f"Order {payload.order_id} verification result: {verification_res.status} ({verification_res.decision}).",
    )

    return verification_res
