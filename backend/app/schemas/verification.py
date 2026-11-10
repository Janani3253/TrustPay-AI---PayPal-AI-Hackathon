from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    PASSED = "Passed"
    FAILED = "Failed"
    NEEDS_REVIEW = "Needs Review"


class OverallDecision(str, Enum):
    BLOCKED = "BLOCKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"


class BackendVerificationCheck(BaseModel):
    name: str = Field(description="Name or title of the verification rule")
    status: Literal["Passed", "Failed", "Needs Review"] = Field(
        description="Check result: Passed, Failed, or Needs Review"
    )
    reason: str = Field(description="Deterministic explanation or evidence")
    critical: bool = Field(
        default=True,
        description="Whether failure of this check strictly blocks checkout",
    )


class VerificationTotals(BaseModel):
    subtotal: float
    shipping: float
    tax: float
    total: float
    currency: Literal["USD", "INR"] = "USD"


class BackendVerification(BaseModel):
    """
    Contract strictly matching frontend/src/types/index.ts BackendVerification interface.
    """
    order_id: str
    order_version: int
    status: Literal["Passed", "Failed"]
    checks: List[BackendVerificationCheck]
    totals: VerificationTotals
    decision: Optional[OverallDecision] = None

