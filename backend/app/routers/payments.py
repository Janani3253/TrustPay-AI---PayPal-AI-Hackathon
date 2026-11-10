"""FastAPI router for PayPal Sandbox Payment Integration."""

from typing import Any, Dict
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user
from app.schemas.payment import (
    PaymentCreateOrderRequest,
    PaymentCreateOrderResponse,
    PaymentCaptureRequest,
    PaymentCaptureResponse,
)
from app.services.paypal_service import paypal_service

router = APIRouter(prefix="/api/payments", tags=["Payments"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post(
    "/create-order",
    response_model=PaymentCreateOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Create PayPal Sandbox Checkout Order",
    description="Validates IntentLock customer approval and initiates genuine or simulated PayPal Sandbox checkout.",
)
async def create_payment_order(
    payload: PaymentCreateOrderRequest,
    user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create PayPal Sandbox checkout order."""
    user_id = _extract_user_id(user)
    return await paypal_service.create_checkout_order(
        order_id=payload.order_id,
        user_id=user_id,
    )


@router.post(
    "/capture-order",
    response_model=PaymentCaptureResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture PayPal Sandbox Checkout Order",
    description="Captures the authorized PayPal transaction, updates order status, and generates a verified transaction record.",
)
async def capture_payment_order(
    payload: PaymentCaptureRequest,
    user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Capture PayPal Sandbox checkout order."""
    user_id = _extract_user_id(user)
    return await paypal_service.capture_checkout_order(
        paypal_order_id=payload.paypal_order_id,
        user_id=user_id,
    )

