from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.verification import BackendVerificationCheck, VerificationTotals


class IntentLockCreateRequest(BaseModel):
    """Payload to create or initialize an IntentLock purchase-intent record."""
    model_config = ConfigDict(extra="ignore")

    intent: Dict[str, Any] = Field(description="Structured customer purchase intent")
    product_id: Optional[int] = Field(default=None, description="Approved or selected product ID")
    quantity: int = Field(default=1, ge=1, le=100, description="Approved quantity")


class IntentLockRecord(BaseModel):
    """Structured purchase-intent record per task specification."""
    model_config = ConfigDict(extra="allow")

    intent_id: str = Field(description="Unique IntentLock record identifier (order ID)")
    original_request: str = Field(description="Exact original customer request")
    approved_product_id: Optional[int] = Field(default=None, description="Approved product identifier")
    product_name_and_brand: Optional[str] = Field(default=None, description="Product title and brand")
    maximum_budget: float = Field(description="Maximum authorized budget limit")
    approved_quantity: int = Field(default=1, description="Approved item quantity")
    currency: str = Field(default="USD", description="Authorized currency code")
    required_specifications: List[Dict[str, str]] = Field(default_factory=list, description="Customer mandatory specifications")
    approved_seller: Optional[str] = Field(default=None, description="Approved seller identifier")
    customer_approval_status: str = Field(default="PENDING", description="Customer approval status (PENDING, APPROVED, REJECTED, REVOKED)")
    version: int = Field(default=1, description="Version of the purchase intent record")
    status: str = Field(default="pending_verification", description="Verification/order status")
    totals: Dict[str, Any] = Field(default_factory=dict, description="Server-calculated price breakdown")
    items: List[Dict[str, Any]] = Field(default_factory=list, description="Cart items snapshot")
    snapshot_hash: str = Field(default="", description="SHA-256 fingerprint of purchase conditions")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IntentLockVerifyRequest(BaseModel):
    """Payload to trigger IntentLock verification."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str = Field(description="IntentLock purchase-intent record ID (order ID)")


class IntentLockVerifyResponse(BaseModel):
    """Detailed verification report categorized across all security layers."""
    model_config = ConfigDict(extra="allow")

    intent_id: str
    version: int
    status: Literal["Passed", "Failed", "Needs Review"]
    decision: str = Field(description="READY_FOR_APPROVAL, BLOCKED, or NEEDS_REVIEW")
    product_verification: Dict[str, Any]
    price_verification: Dict[str, Any]
    cart_verification: Dict[str, Any]
    website_security_verification: Dict[str, Any]
    checks: List[BackendVerificationCheck]
    totals: VerificationTotals
    verified_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IntentLockApproveRequest(BaseModel):
    """Payload for customer explicit purchase approval."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str = Field(description="IntentLock record ID")
    version: int = Field(description="Verified record version being approved")


class IntentLockApproveResponse(BaseModel):
    """Response after recording customer approval."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str
    version: int
    status: str = "approved"
    approved_at: str
    snapshot_hash: str


class IntentLockReverifyRequest(BaseModel):
    """Payload for immediate pre-checkout reverification."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str = Field(description="IntentLock record ID")


class IntentLockReverifyResponse(BaseModel):
    """Response from immediate pre-payment reverification."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str
    reverification_passed: bool
    payment_allowed: bool
    status: str
    reason: str
    current_cart_total: float
    approved_total: float
    currency: str
    reverified_at: str


class IntentLockAuditResponse(BaseModel):
    """Cryptographic audit trail for IntentLock purchase intent."""
    model_config = ConfigDict(extra="ignore")

    intent_id: str
    chain_valid: bool
    records_count: int
    events: List[Dict[str, Any]]

