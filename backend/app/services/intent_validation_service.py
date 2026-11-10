import re
from decimal import Decimal
from typing import List, Tuple
from app.schemas.intent import (
    BudgetSpecification,
    ExcludedCondition,
    MandatorySpecification,
    PreferenceSpecification,
    StructuredIntentExtraction,
)


class IntentValidationService:
    """
    Independent validation layer for Gemini AI outputs.
    Ensures that AI-extracted specifications and budgets are strictly substantiated
    by evidence within the customer's original text, detects contradictions,
    and enforces safety constraints.
    """

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize whitespace and casing for reliable substring evidence verification."""
        return " ".join(text.lower().split())

    @classmethod
    def verify_evidence(cls, customer_request: str, evidence: str | None) -> bool:
        """Verify that claimed evidence actually appears in the customer request."""
        if not evidence or not evidence.strip():
            return False
        norm_request = cls._normalize_text(customer_request)
        norm_evidence = cls._normalize_text(evidence)
        return norm_evidence in norm_request

    @classmethod
    def validate_and_normalize(
        cls,
        customer_request: str,
        extraction: StructuredIntentExtraction,
    ) -> StructuredIntentExtraction:
        """
        Validate extracted intent against the customer's original text.
        Marks unsupported or contradictory claims as unresolved and requests clarification.
        """
        validated_specs: List[MandatorySpecification] = []
        validated_prefs: List[PreferenceSpecification] = []
        validated_exclusions: List[ExcludedCondition] = []
        unresolved: List[str] = list(extraction.unresolved_requirements)
        warnings: List[str] = list(extraction.extraction_warnings)
        clarification_questions: List[str] = list(extraction.clarification_questions)
        clarification_required = extraction.clarification_required

        # 1. Validate Product Type
        if not extraction.product_type or extraction.product_type.strip().lower() in ("unknown", "product", "item", "something"):
            clarification_required = True
            if "Which specific product type are you looking for?" not in clarification_questions:
                clarification_questions.append("Which specific product type are you looking for?")
            unresolved.append("Product type is missing or too generic.")

        # 2. Validate Budget Constraints
        budget = extraction.budget
        if budget and budget.amount is not None:
            if budget.evidence and not cls.verify_evidence(customer_request, budget.evidence):
                warnings.append(f"Budget evidence '{budget.evidence}' could not be verified in customer request.")
            if budget.amount <= Decimal("0.00"):
                budget = None
                clarification_required = True
                clarification_questions.append("What is your maximum budget for this purchase?")
                unresolved.append("Budget amount must be greater than zero.")

        # 3. Validate Mandatory Specifications & Evidence
        seen_specs = {}
        for spec in extraction.mandatory_specifications:
            if spec.evidence and not cls.verify_evidence(customer_request, spec.evidence):
                unresolved.append(f"Specification '{spec.name}' ('{spec.value}') lacks verifiable evidence in text.")
                clarification_required = True
            else:
                validated_specs.append(spec)
                # Check for direct conflicts (e.g. min 16GB RAM vs max 8GB RAM)
                key = spec.name.strip().lower()
                if key in seen_specs:
                    prior = seen_specs[key]
                    if prior.operator != spec.operator and prior.value != spec.value:
                        clarification_required = True
                        unresolved.append(f"Contradictory requirements found for '{spec.name}': {prior.operator} {prior.value} vs {spec.operator} {spec.value}")
                        clarification_questions.append(f"Please clarify your requirement for {spec.name}.")
                seen_specs[key] = spec

        # 4. Validate Preferences
        for pref in extraction.preferences:
            if pref.evidence and not cls.verify_evidence(customer_request, pref.evidence):
                warnings.append(f"Preference '{pref.name}' evidence '{pref.evidence}' not found in request.")
            validated_prefs.append(pref)

        # 5. Validate Excluded Conditions
        for excl in extraction.excluded_conditions:
            if excl.evidence and not cls.verify_evidence(customer_request, excl.evidence):
                warnings.append(f"Exclusion '{excl.condition}' evidence not strictly verified.")
            validated_exclusions.append(excl)

        # 6. Validate Quantity
        qty = extraction.quantity
        if qty < 1:
            qty = 1

        return StructuredIntentExtraction(
            product_type=extraction.product_type,
            product_category=extraction.product_category,
            search_keywords=extraction.search_keywords,
            budget=budget,
            mandatory_specifications=validated_specs,
            preferences=validated_prefs,
            excluded_conditions=validated_exclusions,
            quantity=qty,
            clarification_required=clarification_required,
            clarification_questions=clarification_questions,
            unresolved_requirements=unresolved,
            extraction_warnings=warnings,
        )


intent_validation_service = IntentValidationService()

