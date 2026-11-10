"""Pydantic schemas for Approval operations."""

from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    order_version: int = Field(..., description="Target order version to approve")


class ApprovalResponse(BaseModel):
    order_id: str
    order_version: int
    status: str = "approved"

