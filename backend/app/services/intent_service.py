import logging
import re
from typing import Any, Dict, List, Optional
from app.core.ai_exceptions import AINotConfiguredError
from app.core.config import settings
from app.schemas.intent import (
    PurchaseIntentResponse,
    PurchaseRequirement,
    StructuredIntentExtraction,
)
from app.schemas import IntentRequest
from app.services.gemini_service import GeminiService, gemini_service
from app.services.intent_validation_service import IntentValidationService, intent_validation_service

logger = logging.getLogger(__name__)


class IntentService:
    """
    Orchestration service for customer shopping intent extraction.
    Coordinates Gemini AI extraction, rigorous evidence validation, and
    backward-compatible formatting for the React frontend.
    """

    def __init__(
        self,
        gemini: Optional[GeminiService] = None,
        validator: Optional[IntentValidationService] = None,
    ):
        self._gemini = gemini or gemini_service
        self._validator = validator or intent_validation_service

    async def parse_shopping_intent(
        self,
        payload: IntentRequest,
    ) -> PurchaseIntentResponse:
        """
        Extract structured shopping policy from customer natural-language request.
        Validates against evidence in text and formats for IntentLock verification.
        """
        # If Gemini is not configured, raise explicit AI_NOT_CONFIGURED error
        if not settings.is_gemini_configured:
            raise AINotConfiguredError(
                "Gemini AI is not configured. Please configure GEMINI_API_KEY in backend/.env to enable natural-language intent extraction."
            )

        # 1. Execute AI Extraction
        raw_extraction: StructuredIntentExtraction = await self._gemini.extract_shopping_intent(
            customer_request=payload.request
        )

        # 2. Validate extracted fields against customer request text
        validated: StructuredIntentExtraction = self._validator.validate_and_normalize(
            customer_request=payload.request,
            extraction=raw_extraction,
        )

        # 3. Format requirements for frontend Display
        frontend_requirements: List[PurchaseRequirement] = []
        for spec in validated.mandatory_specifications:
            val_str = f"{spec.value} {spec.unit or ''}".strip()
            frontend_requirements.append(
                PurchaseRequirement(name=spec.name, value=val_str)
            )

        # Format Category
        category = payload.category or validated.product_category or ""

        # Format Budget (preserves customer specified budget if not superseded by valid extracted budget)
        budget = float(payload.maximumBudget)
        if validated.budget and validated.budget.amount is not None:
            budget = float(validated.budget.amount)

        # Format Currency
        currency = payload.currency
        if validated.budget and validated.budget.currency in ("USD", "INR"):
            currency = validated.budget.currency

        # Detect Excluded Accessories
        exclude_accessories = any(
            excl.condition.lower() in ("accessory", "accessories")
            for excl in validated.excluded_conditions
        ) or bool(re.search(r"\b(?:do not|don't|no)\s+add\s+accessories\b", payload.request, re.I))

        # Status
        status_state = "CLARIFICATION_REQUIRED" if validated.clarification_required else "READY_FOR_REVIEW"

        return PurchaseIntentResponse(
            request=payload.request,
            category=category,
            requirements=frontend_requirements,
            maximumBudget=budget,
            currency=currency,
            trustedSellersOnly=payload.trustedSellersOnly,
            platformId=payload.platformId,
            excludeAccessories=exclude_accessories,
            structured_intent=validated,
            extraction_method="GEMINI",
            model=settings.GEMINI_MODEL,
            status=status_state,
            clarification_required=validated.clarification_required,
            clarification_questions=validated.clarification_questions,
            unresolved_requirements=validated.unresolved_requirements,
        )

    async def close(self) -> None:
        """Release underlying AI service resources."""
        await self._gemini.close()


intent_service = IntentService()

