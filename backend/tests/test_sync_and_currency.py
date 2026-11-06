import pytest
from app.schemas.intent import AnalyzeIntentRequest
from app.services.currency_service import currency_service, USD_TO_INR_RATE
from app.services.intent_service import intent_service


@pytest.mark.asyncio
async def test_user_scenario_headphones_1000_black():
    """Test scenario 1: 'i need headphones under 1000 in black color'."""
    req = AnalyzeIntentRequest(
        request="i need headphones under 1000 in black color",
        platformId="dummyjson",
        currency="USD",
    )
    res = await intent_service.analyze_shopping_intent(req)

    assert res.intent.category == "Headphones"
    assert res.intent.max_budget == 1000.0
    assert res.intent.currency == "USD"
    assert res.intent.quantity == 1
    assert any("Black" in f for f in res.intent.features)
    assert res.original_request == "i need headphones under 1000 in black color"


@pytest.mark.asyncio
async def test_user_scenario_different_category_replaces_previous():
    """Test scenario 2: Different category and budget replaces previous."""
    req = AnalyzeIntentRequest(
        request="i want a gaming laptop under 1200 with 16GB RAM and 512GB SSD",
        platformId="dummyjson",
        currency="USD",
    )
    res = await intent_service.analyze_shopping_intent(req)

    assert res.intent.category == "laptops"
    assert res.intent.max_budget == 1200.0
    assert any("16GB RAM" in f for f in res.intent.features)
    assert res.original_request == "i want a gaming laptop under 1200 with 16GB RAM and 512GB SSD"


@pytest.mark.asyncio
async def test_user_scenario_explicit_inr_currency():
    """Test scenario 3: Explicit INR in prompt."""
    req = AnalyzeIntentRequest(
        request="i need headphones under ₹2500 in black color",
        platformId="dummyjson",
    )
    res = await intent_service.analyze_shopping_intent(req)

    assert res.intent.category == "Headphones"
    assert res.intent.max_budget == 2500.0
    assert res.intent.currency == "INR"
    assert res.currency == "INR"


@pytest.mark.asyncio
async def test_user_scenario_currency_conversion_service():
    """Test scenario 4: Authoritative currency conversion."""
    converted_usd = currency_service.convert(8300.0, "INR", "USD")
    assert converted_usd == 100.0

    converted_inr = currency_service.convert(100.0, "USD", "INR")
    assert converted_inr == 8300.0

    symbol_usd = currency_service.get_symbol("USD")
    assert symbol_usd == "$"

    symbol_inr = currency_service.get_symbol("INR")
    assert symbol_inr == "₹"


@pytest.mark.asyncio
async def test_user_scenario_missing_fields_graceful_handling():
    """Test scenario 5: Missing budget does not fabricate values."""
    req = AnalyzeIntentRequest(
        request="looking for stylish shoes",
        platformId="dummyjson",
    )
    res = await intent_service.analyze_shopping_intent(req)

    assert res.intent.category == "mens-shoes"
    assert res.intent.max_budget is None
    assert res.intent.quantity == 1

