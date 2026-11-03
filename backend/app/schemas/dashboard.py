"""Pydantic schemas for Dashboard metrics."""

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class DashboardMetricsResponse(BaseModel):
    total_requests: int
    verified_orders: int
    blocked_transactions: int
    recent_transactions: List[Dict[str, Any]] = Field(default_factory=list)
    security_activity: List[Dict[str, Any]] = Field(default_factory=list)

