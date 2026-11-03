from pydantic import BaseModel, Field
from typing import Literal

from .auth import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    AuthResponse,
    LogoutResponse,
    UserProfileResponse,
)
from .product import (
    NormalizedProduct,
    ProductListResponse,
    ProductCategory,
    ShoppingPlatformResponse,
)
from .intent import (
    BudgetSpecification,
    MandatorySpecification,
    PreferenceSpecification,
    ExcludedCondition,
    StructuredIntentExtraction,
    PurchaseRequirement,
    PurchaseIntentResponse,
)
from .security import (
    SeverityLevel,
    AttackCategory,
    RiskLevel,
    AnalysisStatus,
    AnalysisMode,
    DetectionMethod,
    SecurityFinding,
    ProductSecurityScanRequest,
    ProductSecurityScanResponse,
    GeminiSecurityFinding,
    GeminiSecurityAnalysis,
)


class IntentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    maximumBudget: float = Field(gt=0)
    currency: Literal["USD", "INR"] = "USD"
    category: str = ""
    trustedSellersOnly: bool = True
    platformId: str = "dummyjson"


class OrderRequest(BaseModel):
    intent: dict


class VerifyOrderRequest(BaseModel):
    order_id: str


class ApprovalRequest(BaseModel):
    order_version: int = Field(ge=1)


class CartItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=99)


class CartQuantityRequest(BaseModel):
    quantity: int = Field(ge=1, le=99)


class PayPalCaptureRequest(BaseModel):
    paypal_order_id: str = Field(min_length=1, max_length=128)


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "UserResponse",
    "AuthResponse",
    "LogoutResponse",
    "UserProfileResponse",
    "NormalizedProduct",
    "ProductListResponse",
    "ProductCategory",
    "ShoppingPlatformResponse",
    "BudgetSpecification",
    "MandatorySpecification",
    "PreferenceSpecification",
    "ExcludedCondition",
    "StructuredIntentExtraction",
    "PurchaseRequirement",
    "PurchaseIntentResponse",
    "IntentRequest",
    "OrderRequest",
    "VerifyOrderRequest",
    "ApprovalRequest",
    "CartItemRequest",
    "CartQuantityRequest",
    "PayPalCaptureRequest",
]

