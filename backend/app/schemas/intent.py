from decimal import Decimal, ROUND_HALF_UP
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


BudgetComparisonType = Literal["MAXIMUM", "MINIMUM", "EXACT", "RANGE"]
BudgetScopeType = Literal["PRODUCT_ONLY", "FINAL_CHECKOUT_TOTAL", "UNSPECIFIED"]


class BudgetSpecification(BaseModel):
    """Normalized budget constraint extracted from customer shopping request."""
    model_config = ConfigDict(extra="ignore")

    amount: Optional[Decimal] = Field(default=None, description="Numerical budget limit")
    currency: Optional[str] = Field(default=None, description="Currency code (USD, INR, etc.)")
    comparison: BudgetComparisonType = Field(default="MAXIMUM", description="Comparison type")
    scope: BudgetScopeType = Field(default="UNSPECIFIED", description="Scope of budget")
    evidence: Optional[str] = Field(default=None, description="Exact phrase in customer text")

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Optional[Decimal]:
        if v is None or v == "":
            return None
        try:
            d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if d < Decimal("0.00"):
                raise ValueError("Budget amount cannot be negative")
            if d > Decimal("100000000.00"):
                raise ValueError("Budget amount exceeds permissible limit")
            return d
        except Exception as err:
            raise ValueError(f"Invalid monetary amount: {v}") from err


class MandatorySpecification(BaseModel):
    """Technical or physical specification required for purchase verification."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Normalized parameter name (e.g. RAM, Storage, Processor)")
    operator: str = Field(default="GTE", description="Operator: GTE, LTE, EQ, CONTAINS")
    value: str = Field(description="Required parameter value (e.g. 16, 512, Intel i7)")
    unit: Optional[str] = Field(default=None, description="Measurement unit (e.g. GB, SSD, inches)")
    evidence: Optional[str] = Field(default=None, description="Exact quote from customer request")


class PreferenceSpecification(BaseModel):
    """Optional preference that does not invalidate an item if unmet."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Preference parameter name (e.g. Brand, Color)")
    preference_type: str = Field(default="PREFERRED", description="Preference qualifier")
    value: str = Field(description="Preferred parameter value (e.g. ASUS, Black)")
    evidence: Optional[str] = Field(default=None, description="Exact quote from customer request")


class ExcludedCondition(BaseModel):
    """Explicitly excluded product characteristic (e.g. refurbished, accessories)."""
    model_config = ConfigDict(extra="ignore")

    condition: str = Field(description="Excluded characteristic (e.g. refurbished, damaged, accessories)")
    evidence: Optional[str] = Field(default=None, description="Exact quote from customer request")


class StructuredIntentExtraction(BaseModel):
    """
    Structured Gemini output model. Schema-constrained during AI generation.
    """
    model_config = ConfigDict(extra="ignore")

    product_type: Optional[str] = Field(default=None, description="General product type (e.g. laptop, smartphone)")
    product_category: Optional[str] = Field(default=None, description="Catalogue category slug (e.g. laptops, beauty)")
    search_keywords: List[str] = Field(default_factory=list, description="Extracted search keywords")
    budget: Optional[BudgetSpecification] = Field(default=None, description="Budget constraint")
    mandatory_specifications: List[MandatorySpecification] = Field(
        default_factory=list,
        description="Mandatory conditions for purchase",
    )
    preferences: List[PreferenceSpecification] = Field(
        default_factory=list,
        description="Optional customer preferences",
    )
    excluded_conditions: List[ExcludedCondition] = Field(
        default_factory=list,
        description="Explicitly excluded product conditions",
    )
    quantity: int = Field(default=1, ge=1, le=100, description="Requested product count")
    brand: List[str] = Field(default_factory=list, description="Extracted brand names or preferences")
    features: List[str] = Field(default_factory=list, description="Extracted required product features")
    clarification_required: bool = Field(default=False, description="Whether request is ambiguous or incomplete")
    clarification_questions: List[str] = Field(
        default_factory=list,
        description="Specific clarifying questions if ambiguous",
    )
    unresolved_requirements: List[str] = Field(
        default_factory=list,
        description="Requirements lacking clear evidence or contradictory",
    )
    extraction_warnings: List[str] = Field(default_factory=list, description="Non-fatal extraction warnings")


class PurchaseRequirement(BaseModel):
    """Requirement format matching frontend PurchaseRequirement interface."""
    model_config = ConfigDict(extra="ignore")

    name: str
    value: str


class PurchaseIntentResponse(BaseModel):
    """
    Unified API response model for POST /api/intent/parse.
    Fully satisfies frontend's PurchaseIntent interface while exposing rich AI metadata.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Core Frontend Contract Fields (Required by frontend/src/types/index.ts)
    request: str = Field(description="Exact original customer shopping request")
    category: str = Field(default="", description="Mapped category slug")
    requirements: List[PurchaseRequirement] = Field(
        default_factory=list,
        description="Key-value specifications for frontend display",
    )
    maximumBudget: float = Field(description="Effective numerical maximum budget")
    currency: Literal["USD", "INR"] = Field(default="USD", description="Currency of budget")
    trustedSellersOnly: bool = Field(default=True, description="Seller trust preference")
    platformId: str = Field(default="dummyjson", description="Target shopping platform")
    excludeAccessories: bool = Field(default=False, description="Whether accessories are excluded")

    # Extra Normalized IntentLock Fields
    structured_intent: Optional[StructuredIntentExtraction] = Field(
        default=None,
        description="Deep structured intent representation",
    )
    extraction_method: str = Field(default="GEMINI", description="GEMINI or FALLBACK")
    model: Optional[str] = Field(default=None, description="Model identifier used for extraction")
    status: str = Field(default="READY_FOR_REVIEW", description="Extraction readiness state")
    clarification_required: bool = Field(default=False, description="Flag indicating need for customer clarification")
    clarification_questions: List[str] = Field(default_factory=list, description="Clarifying questions")
    unresolved_requirements: List[str] = Field(default_factory=list, description="Unresolved constraints")


class ExtractedIntentData(BaseModel):
    """
    Standard customer intent structure matching task specification:
    category, brand, max_budget, currency, features, quantity.
    """
    model_config = ConfigDict(extra="ignore")

    category: str = Field(default="", description="Product category")
    brand: List[str] = Field(default_factory=list, description="Extracted brand preferences")
    max_budget: Optional[float] = Field(default=None, description="Maximum budget limit")
    currency: str = Field(default="USD", description="Currency code (USD, INR, etc.)")
    features: List[str] = Field(default_factory=list, description="Required product features")
    quantity: int = Field(default=1, ge=1, description="Requested quantity")


class AnalyzeIntentRequest(BaseModel):
    """Request payload for POST /ai/analyze-intent."""
    model_config = ConfigDict(extra="ignore")

    request: str = Field(..., min_length=1, max_length=2000, description="Natural-language customer shopping request")
    category: Optional[str] = Field(default="", description="Optional category hint")
    maximumBudget: Optional[float] = Field(default=None, description="Optional customer budget limit")
    currency: Optional[str] = Field(default=None, description="Optional currency code")
    platformId: str = Field(default="dummyjson", description="Target shopping platform")
    trustedSellersOnly: bool = Field(default=True, description="Require trusted sellers")


class AnalyzeIntentResponse(BaseModel):
    """
    Unified response for POST /ai/analyze-intent.
    Returns original request stored separately from structured intent,
    while providing backward compatibility with existing frontend types.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    original_request: str = Field(description="Exact original customer shopping request")
    intent: ExtractedIntentData = Field(description="Structured purchase intent")
    clarification_required: bool = Field(default=False)
    clarification_questions: List[str] = Field(default_factory=list)
    extraction_method: str = Field(default="GEMINI", description="GEMINI or RULE_BASED_FALLBACK")
    status: str = Field(default="READY_FOR_REVIEW")

    # Backward compatibility with frontend PurchaseIntent interface
    request: str = Field(default="", description="Original request alias")
    category: str = Field(default="", description="Category alias")
    requirements: List[PurchaseRequirement] = Field(default_factory=list)
    maximumBudget: float = Field(default=0.0)
    currency: Literal["USD", "INR"] = Field(default="USD")
    trustedSellersOnly: bool = Field(default=True)
    platformId: str = Field(default="dummyjson")
    excludeAccessories: bool = Field(default=False)
    structured_intent: Optional[StructuredIntentExtraction] = None

