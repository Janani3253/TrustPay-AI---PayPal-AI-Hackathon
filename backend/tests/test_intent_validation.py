from decimal import Decimal
import pytest
from app.schemas.intent import (
    BudgetSpecification,
    ExcludedCondition,
    MandatorySpecification,
    PreferenceSpecification,
    StructuredIntentExtraction,
)
from app.services.intent_validation_service import IntentValidationService


def test_evidence_verification_exact_and_normalized():
    """Verify evidence matcher normalizes whitespace and casing."""
    text = "I need a gaming laptop with at least 16GB RAM and 512GB SSD."
    assert IntentValidationService.verify_evidence(text, "16GB RAM") is True
    assert IntentValidationService.verify_evidence(text, "at   least   16gb   ram") is True
    assert IntentValidationService.verify_evidence(text, "32GB RAM") is False
    assert IntentValidationService.verify_evidence(text, "") is False
    assert IntentValidationService.verify_evidence(text, None) is False


def test_validation_unsupported_evidence_marked_unresolved():
    """Verify specifications without evidence in customer text are flagged as unresolved."""
    customer_text = "I need a laptop with 16GB RAM."
    extraction = StructuredIntentExtraction(
        product_type="laptop",
        mandatory_specifications=[
            MandatorySpecification(name="RAM", operator="GTE", value="16", unit="GB", evidence="16GB RAM"),
            MandatorySpecification(name="GPU", operator="CONTAINS", value="RTX 4060", evidence="RTX 4060 graphics"),
        ],
    )

    validated = IntentValidationService.validate_and_normalize(customer_text, extraction)
    assert validated.clarification_required is True
    assert any("GPU" in u for u in validated.unresolved_requirements)
    # The verified spec is kept
    assert len(validated.mandatory_specifications) == 1
    assert validated.mandatory_specifications[0].name == "RAM"


def test_validation_missing_product_type_flags_clarification():
    """Verify missing or generic product type triggers clarification question."""
    customer_text = "Find me something under $500."
    extraction = StructuredIntentExtraction(
        product_type="something",
        budget=BudgetSpecification(amount=Decimal("500.00"), currency="USD", evidence="under $500"),
    )

    validated = IntentValidationService.validate_and_normalize(customer_text, extraction)
    assert validated.clarification_required is True
    assert any("product type" in q.lower() for q in validated.clarification_questions)
    assert any("Product type is missing" in u for u in validated.unresolved_requirements)


def test_validation_contradictory_specifications_detected():
    """Verify conflicting specs (e.g. 1TB storage vs 512GB) are flagged as unresolved."""
    customer_text = "I need an SSD with at least 1TB storage but maximum 512GB."
    extraction = StructuredIntentExtraction(
        product_type="SSD",
        mandatory_specifications=[
            MandatorySpecification(name="storage", operator="GTE", value="1TB", evidence="at least 1TB storage"),
            MandatorySpecification(name="storage", operator="LTE", value="512GB", evidence="maximum 512GB"),
        ],
    )

    validated = IntentValidationService.validate_and_normalize(customer_text, extraction)
    assert validated.clarification_required is True
    assert any("Contradictory" in u for u in validated.unresolved_requirements)
    assert any("clarify" in q.lower() for q in validated.clarification_questions)


def test_validation_budget_boundary_checks():
    """Verify negative and zero budgets are rejected."""
    with pytest.raises(Exception):
        BudgetSpecification(amount=Decimal("-50.00"), currency="USD")

    # Extremely large amount (> 100M)
    with pytest.raises(Exception):
        BudgetSpecification(amount=Decimal("999999999999.00"), currency="USD")

