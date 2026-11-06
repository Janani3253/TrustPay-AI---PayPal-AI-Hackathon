"""Pydantic schemas for PayPal Sandbox Payment Integration."""

from typing import Optional
from pydantic import BaseModel, Field


class PaymentCreateOrderRequest(BaseModel):
    order_id: str = Field(..., description="TrustPay Order ID to create PayPal checkout for")


class PaymentCreateOrderResponse(BaseModel):
    order_id: str
    paypal_order_id: str
    approval_url: str
    status: str = "PENDING"


class PaymentCaptureRequest(BaseModel):
    paypal_order_id: str = Field(..., description="PayPal Sandbox checkout order ID to capture")


class PaymentCaptureResponse(BaseModel):
    id: Optional[str] = None
    order_id: str
    paypal_reference: str
    amount: float
    currency: str
    date: str
    status: str
    method: str = "PayPal Sandbox"

