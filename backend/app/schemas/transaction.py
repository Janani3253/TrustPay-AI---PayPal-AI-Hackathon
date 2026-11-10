"""Pydantic schemas for Transactions."""

from typing import Optional
from pydantic import BaseModel, Field


class TransactionResponse(BaseModel):
    id: str
    order_id: str = Field(..., alias="order_id")
    orderId: Optional[str] = Field(default=None, alias="orderId")
    product: str
    amount: float
    currency: str = "USD"
    date: str
    method: str = "PayPal Sandbox"
    status: str = "Completed"
    verification: str = "Backend verified"
    paypal_reference: Optional[str] = Field(default=None, alias="paypal_reference")
    paypalReference: Optional[str] = Field(default=None, alias="paypalReference")

    class Config:
        populate_by_name = True

