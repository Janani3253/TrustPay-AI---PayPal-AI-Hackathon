"""Pydantic schemas for Audit events and verification."""

from typing import Optional
from pydantic import BaseModel, Field


class AuditEventResponse(BaseModel):
    id: str
    type: str
    timestamp: str
    description: str
    previousHash: str
    hash: str
    integrity: Optional[str] = "Pending"


class AuditVerificationResponse(BaseModel):
    valid: bool
    records_checked: int

