"""Pydantic schemas for Order operations."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class OrderTotals(BaseModel):
    subtotal: float = 0.0
    tax: float = 0.0
    shipping: float = 0.0
    total: float = 0.0
    currency: str = "USD"


class OrderItemSchema(BaseModel):
    product: dict[str, Any]
    quantity: int = 1


class OrderCreateRequest(BaseModel):
    intent: dict[str, Any] = Field(..., description="Customer natural language purchase intent")


class OrderResponse(BaseModel):
    id: str
    version: int = 1
    status: str = "pending_verification"
    items: list[dict[str, Any]] = Field(default_factory=list)
    intent: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    checks: Optional[dict[str, Any]] = None
    paypal_order_id: Optional[str] = None

