"""FastAPI router for AI Intent Analysis and Intelligent Recommendations."""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.audit import add_audit
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.intent import AnalyzeIntentRequest, AnalyzeIntentResponse
from app.schemas.recommendation import RecommendationResponse
from app.services.intent_service import intent_service
from app.services.recommendation_service import recommendation_service

router = APIRouter(tags=["AI"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post(
    "/ai/analyze-intent",
    response_model=AnalyzeIntentResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze natural-language shopping instruction using Gemini AI",
    description="Extracts category, brand, budget, currency, features, and quantity. Stores original customer request separately from intent.",
)
@router.post(
    "/api/ai/analyze-intent",
    response_model=AnalyzeIntentResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def analyze_intent(
    payload: AnalyzeIntentRequest,
    user: User = Depends(get_current_user),
) -> AnalyzeIntentResponse:
    """Analyze customer shopping request and extract verified purchase policy."""
    user_id = _extract_user_id(user)
    try:
        result = await intent_service.analyze_shopping_intent(payload)
        add_audit(
            user_id=user_id,
            event_type="AI_INTENT_ANALYZED",
            description=f"Extracted intent for category '{result.intent.category}' ({result.extraction_method}).",
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intent analysis failed: {exc}",
        ) from exc


@router.post(
    "/ai/recommendations",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get AI-powered product recommendations scored against customer intent",
    description="Calculates normalized recommendation scores (35% Brand + 30% Price + 20% Features + 15% Rating). Never recommends products violating budget.",
)
@router.post(
    "/api/ai/recommendations",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_ai_recommendations(
    payload: Dict[str, Any],
    user: User = Depends(get_current_user),
) -> RecommendationResponse:
    """Evaluate catalogue products and compute normalized recommendation scores."""
    user_id = _extract_user_id(user)
    intent_data = payload.get("intent", payload)
    if not isinstance(intent_data, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Valid intent parameters required.",
        )

    try:
        limit = int(payload.get("limit", 50))
        results = await recommendation_service.get_recommendations(intent_data=intent_data, limit=limit)
        add_audit(
            user_id=user_id,
            event_type="AI_RECOMMENDATIONS_RETRIEVED",
            description=f"Scored {results.total} product recommendations against intent.",
        )
        return results
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recommendation computation failed: {exc}",
        ) from exc

