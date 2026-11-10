from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MatchTier(str, Enum):
    FULL_MATCH = "FULL MATCH"
    PARTIAL_MATCH = "PARTIAL MATCH"
    NOT_VERIFIED = "NOT VERIFIED"
    EXCLUDED = "EXCLUDED"


class RecommendationScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category_match_score: float = Field(default=0.0, description="Points from category match (0 - 30)")
    feature_match_score: float = Field(default=0.0, description="Points from feature match (0 - 25)")
    price_suitability_score: float = Field(default=0.0, description="Points from price suitability (0 - 20)")
    brand_match_score: float = Field(default=0.0, description="Points from brand match (0 - 15)")
    rating_score: float = Field(default=0.0, description="Points from product rating (0 - 10)")
    total_score: float = Field(default=0.0, description="Normalized total recommendation score (0 - 100)")
    normalized_score: float = Field(default=0.0, description="Normalized recommendation score (0.0 - 1.0)")


class RequirementMatchItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    requested: str
    status: str  # "Matched", "Not matched", "Not verified"
    explanation: str
    verified: bool = True


class ProductRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    product: Dict[str, Any]
    score: float = Field(description="Normalized recommendation score (0 - 100)")
    normalized_score: float = Field(default=0.0, description="Normalized score (0.0 - 1.0)")
    match_tier: MatchTier = Field(default=MatchTier.NOT_VERIFIED, description="Recommendation compliance tier")
    is_fully_matching: bool = Field(description="Whether all mandatory customer requirements and budget constraints are met and verified")
    breakdown: RecommendationScoreBreakdown
    recommendation_reason: str
    mismatch_reasons: List[str] = Field(default_factory=list)
    unverified_features: List[str] = Field(default_factory=list)
    analysis: Dict[str, Any] = Field(description="Frontend compatibility analysis structure")


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    total: int
    full_matches_count: int = 0
    recommendations: List[ProductRecommendationItem]
