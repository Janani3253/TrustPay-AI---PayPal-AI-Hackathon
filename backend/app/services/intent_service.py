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


import logging
import re
from typing import Any, Dict, List, Optional
from decimal import Decimal
from app.core.ai_exceptions import AINotConfiguredError
from app.core.config import settings
from app.schemas.intent import (
    AnalyzeIntentRequest,
    AnalyzeIntentResponse,
    BudgetSpecification,
    ExtractedIntentData,
    MandatorySpecification,
    PreferenceSpecification,
    PurchaseIntentResponse,
    PurchaseRequirement,
    StructuredIntentExtraction,
)
from app.schemas import IntentRequest
from app.services.gemini_service import GeminiService, gemini_service
from app.services.intent_validation_service import IntentValidationService, intent_validation_service

logger = logging.getLogger(__name__)


KNOWN_BRANDS = [
    "Sony", "Apple", "Samsung", "Dell", "HP", "Lenovo", "ASUS", "Acer", "Bose",
    "Sennheiser", "JBL", "Audio-Technica", "Beats", "Anker", "Google", "OnePlus",
    "Xiaomi", "Motorola", "Nokia", "LG", "Logitech", "Razer", "Corsair", "SteelSeries",
    "Nike", "Adidas", "Puma", "Under Armour", "Rolex", "Casio", "Seiko", "Fossil"
]

CATEGORY_PATTERNS = [
    (r"\b(?:headphones?|earphones?|earbuds?|headset|audio)\b", "Headphones"),
    (r"\b(?:laptop|notebook|computer|pc|ultrabook)\b", "laptops"),
    (r"\b(?:smartphones?|phones?|mobile|iphone|android)\b", "smartphones"),
    (r"\b(?:tablets?|ipad)\b", "tablets"),
    (r"\b(?:smartwatch(?:es)?|watches?)\b", "mens-watches"),
    (r"\b(?:shoes?|sneakers?|boots?)\b", "mens-shoes"),
    (r"\b(?:fragrances?|perfumes?|cologne)\b", "fragrances"),
    (r"\b(?:skincare|beauty|moisturizer|cream)\b", "skin-care"),
    (r"\b(?:groceries|grocery|food|snacks)\b", "groceries"),
]

FEATURE_KEYWORDS = [
    ("wireless", "Wireless"),
    ("bluetooth", "Bluetooth"),
    ("good battery life", "Good battery life"),
    ("long battery life", "Long battery life"),
    ("battery life", "Good battery life"),
    ("noise cancellation", "Noise cancellation"),
    ("noise cancelling", "Noise cancelling"),
    ("anc", "Active Noise Cancellation (ANC)"),
    ("waterproof", "Waterproof"),
    ("water resistant", "Water resistant"),
    ("fast charging", "Fast charging"),
    ("lightweight", "Lightweight"),
    ("compact", "Compact"),
    ("touchscreen", "Touchscreen"),
    ("backlit keyboard", "Backlit keyboard"),
    ("rgb", "RGB"),
    ("5g", "5G"),
    ("4k", "4K Display"),
    ("oled", "OLED"),
]


def extract_budget_and_currency(text: str) -> tuple[Optional[float], Optional[str]]:
    """Extract numerical budget and currency code from text. Returns (budget, currency or None)."""
    detected_currency = None
    if re.search(r"(?:₹|\u20b9|rs\.?|inr|rupees)", text, re.IGNORECASE):
        detected_currency = "INR"
    elif re.search(r"(?:\$|usd|dollars)", text, re.IGNORECASE):
        detected_currency = "USD"

    # Check INR symbols and words: ₹, \u20b9, INR, Rs., rupees
    inr_match = re.search(r"(?:₹|\u20b9|rs\.?|inr)\s*(\d+(?:,\d+)*(?:\.\d+)?)|(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:₹|\u20b9|inr|rupees)", text, re.IGNORECASE)
    if inr_match:
        val_str = (inr_match.group(1) or inr_match.group(2)).replace(",", "")
        try:
            return float(val_str), "INR"
        except ValueError:
            pass

    # Check USD symbols and words: $, USD, dollars
    usd_match = re.search(r"(?:\$|usd)\s*(\d+(?:,\d+)*(?:\.\d+)?)|(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:\$|usd|dollars)", text, re.IGNORECASE)
    if usd_match:
        val_str = (usd_match.group(1) or usd_match.group(2)).replace(",", "")
        try:
            return float(val_str), "USD"
        except ValueError:
            pass

    # Check under / below / max / budget patterns without forcing USD
    under_match = re.search(r"\b(?:under|below|less than|max(?:imum)? budget of|budget(?: of)?)\s*(?:[^\w\s])?\s*(\d+(?:,\d+)*(?:\.\d+)?)", text, re.IGNORECASE)
    if under_match:
        val_str = under_match.group(1).replace(",", "")
        try:
            return float(val_str), detected_currency
        except ValueError:
            pass

    return None, detected_currency


def extract_brands(text: str) -> List[str]:
    """Extract known brand names from text."""
    found = []
    lowered = text.lower()
    for brand in KNOWN_BRANDS:
        pattern = r"\b" + re.escape(brand.lower()) + r"\b"
        if re.search(pattern, lowered):
            found.append(brand)
    return found


def extract_category(text: str, default: str = "") -> str:
    """Identify product category from customer text."""
    lowered = text.lower()
    for pattern, cat in CATEGORY_PATTERNS:
        if re.search(pattern, lowered):
            return cat
    return default or "general"


def extract_features(text: str) -> List[str]:
    """Extract key technical or product features."""
    features = []
    lowered = text.lower()
    for phrase, label in FEATURE_KEYWORDS:
        if phrase in lowered:
            if label not in features:
                features.append(label)
    # Check RAM & Storage
    ram_m = re.search(r"(\d+\s*gb)\s*(?:ram|memory)", lowered)
    if ram_m and f"{ram_m.group(1).upper()} RAM" not in features:
        features.append(f"{ram_m.group(1).upper()} RAM")
    ssd_m = re.search(r"(\d+\s*(?:gb|tb))\s*(?:ssd|storage)", lowered)
    if ssd_m and f"{ssd_m.group(1).upper()} SSD" not in features:
        features.append(f"{ssd_m.group(1).upper()} SSD")
    # Check Color preferences
    color_m = re.search(
        r"\b(?:in\s+)?(black|white|silver|gold|gray|grey|blue|red|green|pink|purple|yellow|matte\s+black|space\s+gray|rose\s+gold)\s*(?:color|colour|finish|edition)?\b",
        lowered,
    )
    if color_m and color_m.group(1):
        color_name = f"{color_m.group(1).title()} color"
        if color_name not in features:
            features.append(color_name)
    return features


def extract_quantity(text: str) -> int:
    """Identify requested quantity."""
    match = re.search(r"\b(\d+)\s*(?:units?|pcs?|pieces?|items?|pairs?|headphones?|laptops?|phones?)\b", text, re.IGNORECASE)
    if match:
        try:
            val = int(match.group(1))
            if 1 <= val <= 100:
                return val
        except ValueError:
            pass
    return 1


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

    def _fallback_extract_intent(
        self,
        text: str,
        category_hint: str = "",
        budget_hint: Optional[float] = None,
        currency_hint: Optional[str] = None,
    ) -> ExtractedIntentData:
        """Deterministic rule-based intent extraction fallback."""
        category = extract_category(text, default=category_hint)
        brands = extract_brands(text)
        features = extract_features(text)
        extracted_budget, extracted_currency = extract_budget_and_currency(text)
        budget = extracted_budget if extracted_budget is not None else budget_hint
        currency = extracted_currency if extracted_currency is not None else (currency_hint if currency_hint in ("USD", "INR") else "USD")
        quantity = extract_quantity(text)

        return ExtractedIntentData(
            category=category,
            brand=brands,
            max_budget=budget,
            currency=currency,
            features=features,
            quantity=quantity,
        )

    async def analyze_shopping_intent(
        self,
        payload: AnalyzeIntentRequest,
    ) -> AnalyzeIntentResponse:
        """
        Primary endpoint implementation for POST /ai/analyze-intent.
        Extracts structured intent with Gemini AI, or deterministic fallback if unavailable.
        Maintains original customer request separately from extracted intent.
        """
        request_text = payload.request.strip()
        extraction_method = "RULE_BASED_FALLBACK"
        clarification_required = False
        clarification_questions: List[str] = []
        structured_raw: Optional[StructuredIntentExtraction] = None

        if settings.is_gemini_configured:
            try:
                structured_raw = await self._gemini.extract_shopping_intent(customer_request=request_text)
                validated = self._validator.validate_and_normalize(
                    customer_request=request_text,
                    extraction=structured_raw,
                )
                extraction_method = "GEMINI"
                clarification_required = validated.clarification_required
                clarification_questions = validated.clarification_questions

                # Extract fields from validated Gemini extraction
                category = validated.product_category or extract_category(request_text, default=payload.category)
                brands = list(validated.brand) if hasattr(validated, "brand") and validated.brand else [
                    p.value for p in validated.preferences if p.name.lower() in ("brand", "preferred_brand")
                ]
                if not brands:
                    brands = extract_brands(request_text)

                features = list(validated.features) if hasattr(validated, "features") and validated.features else [
                    f"{m.name}: {m.value}" for m in validated.mandatory_specifications
                ]
                if not features:
                    features = extract_features(request_text)

                budget_amount = None
                extracted_b, extracted_c = extract_budget_and_currency(request_text)
                budget_currency = extracted_c or (payload.currency if payload.currency in ("USD", "INR") else None) or "USD"
                if validated.budget and validated.budget.amount is not None:
                    budget_amount = float(validated.budget.amount)
                    if validated.budget.currency in ("USD", "INR"):
                        budget_currency = validated.budget.currency
                elif extracted_b is not None:
                    budget_amount = extracted_b
                elif payload.maximumBudget is not None:
                    budget_amount = float(payload.maximumBudget)

                quantity = validated.quantity if validated.quantity >= 1 else 1

                extracted_data = ExtractedIntentData(
                    category=category,
                    brand=brands,
                    max_budget=budget_amount,
                    currency=budget_currency,
                    features=features,
                    quantity=quantity,
                )
            except Exception as exc:
                logger.warning("Gemini AI intent extraction failed, falling back to rule-based: %s", exc)
                extracted_data = self._fallback_extract_intent(
                    text=request_text,
                    category_hint=payload.category or "",
                    budget_hint=payload.maximumBudget,
                    currency_hint=payload.currency,
                )
        else:
            extracted_data = self._fallback_extract_intent(
                text=request_text,
                category_hint=payload.category or "",
                budget_hint=payload.maximumBudget,
                currency_hint=payload.currency,
            )

        # Build frontend requirements list for backward compatibility
        req_list: List[PurchaseRequirement] = []
        for b in extracted_data.brand:
            req_list.append(PurchaseRequirement(name="Brand", value=b))
        for f in extracted_data.features:
            req_list.append(PurchaseRequirement(name="Feature", value=f))

        return AnalyzeIntentResponse(
            original_request=request_text,
            intent=extracted_data,
            clarification_required=clarification_required,
            clarification_questions=clarification_questions,
            extraction_method=extraction_method,
            status="CLARIFICATION_REQUIRED" if clarification_required else "READY_FOR_REVIEW",
            # Backward compatibility fields
            request=request_text,
            category=extracted_data.category,
            requirements=req_list,
            maximumBudget=extracted_data.max_budget or payload.maximumBudget or 1000.0,
            currency=extracted_data.currency if extracted_data.currency in ("USD", "INR") else "USD",
            trustedSellersOnly=payload.trustedSellersOnly,
            platformId=payload.platformId,
            excludeAccessories=False,
            structured_intent=structured_raw,
        )

    async def parse_shopping_intent(
        self,
        payload: IntentRequest,
    ) -> PurchaseIntentResponse:
        """
        Extract structured shopping policy from customer natural-language request.
        Validates against evidence in text and formats for IntentLock verification.
        """
        if settings.is_gemini_configured:
            try:
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

                # Format Budget
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
            except Exception as exc:
                logger.warning("Gemini parsing failed; using rule-based fallback: %s", exc)

        # Fallback path if Gemini is not configured or failed
        extracted = self._fallback_extract_intent(
            payload.request,
            category_hint=payload.category,
            budget_hint=payload.maximumBudget,
            currency_hint=payload.currency,
        )

        reqs = []
        for b in extracted.brand:
            reqs.append(PurchaseRequirement(name="Brand", value=b))
        for f in extracted.features:
            reqs.append(PurchaseRequirement(name="Feature", value=f))

        return PurchaseIntentResponse(
            request=payload.request,
            category=extracted.category,
            requirements=reqs,
            maximumBudget=extracted.max_budget or payload.maximumBudget or 1000.0,
            currency=extracted.currency if extracted.currency in ("USD", "INR") else "USD",
            trustedSellersOnly=payload.trustedSellersOnly,
            platformId=payload.platformId,
            excludeAccessories=False,
            extraction_method="RULE_BASED_FALLBACK",
            model="deterministic-rule-v1",
            status="READY_FOR_REVIEW",
        )

    async def close(self) -> None:
        """Release underlying AI service resources."""
        await self._gemini.close()


intent_service = IntentService()

