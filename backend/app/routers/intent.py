from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.ai_exceptions import AIException
from app.core.audit import add_audit
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas import IntentRequest
from app.schemas.intent import PurchaseIntentResponse
from app.services.intent_service import intent_service

router = APIRouter(prefix="/api/intent", tags=["Intent"])


@router.post(
    "/parse",
    response_model=PurchaseIntentResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract structured purchase policy from natural-language shopping instruction",
    description=(
        "Uses Google Gemini AI to analyze customer shopping text and extract verified, "
        "structured purchase policy requirements, budget constraints, and specifications."
    ),
)
async def parse_intent(
    payload: IntentRequest,
    user: User = Depends(get_current_user),
) -> PurchaseIntentResponse:
    """Analyze customer request and extract structured purchase policy."""
    if payload.platformId != "dummyjson":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the DummyJSON Demo Store is supported.",
        )

    try:
        user_id = int(user["id"] if isinstance(user, dict) else user.id)
        intent = await intent_service.parse_shopping_intent(payload)
        add_audit(
            user_id,
            "Purchase policy created",
            "Created a purchase policy through the Gemini AI intent parser.",
        )
        return intent
    except AIException as ai_err:
        raise HTTPException(
            status_code=ai_err.status_code,
            detail=ai_err.message,
        ) from ai_err
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the shopping intent.",
        ) from exc

