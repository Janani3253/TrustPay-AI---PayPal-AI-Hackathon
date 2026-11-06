"""Automated tests for strict AI product recommendation filtering and ranking.

Covers the 8 mandatory test scenarios:
1. 'Black headphones under 1000' (₹1000 INR = ~$12.05 USD): only headphones within budget, color verified or NOT VERIFIED
2. 'Sony headphones under 2500': only Sony headphones within budget
3. 'Wireless headphones under 3000': only wireless headphones within budget
4. 'Samsung smartphone under 15000': only Samsung smartphones within budget, no cases/chargers
5. 'Red sports shoes under 2000': only red sports shoes within budget
6. 'Headphones under 500': 0 false matches when no catalogue product satisfies criteria
7. 'Black headphones under 1000' when API has no color info: marked NOT VERIFIED and excluded from full match
8. Change shopping request: recommendations immediately update and discard previous results
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.schemas.product import NormalizedProduct, ProductListResponse
from app.schemas.recommendation import MatchTier
from app.services.currency_service import currency_service
from app.services.recommendation_service import recommendation_service


# Mock catalogue data reflecting DummyJSON style products
MOCK_PRODUCTS = [
    # Headphones / Audio
    NormalizedProduct(
        id=101,
        title="Sony WH-CH520 Wireless Bluetooth Headphones",
        description="High quality wireless on-ear headphones with 50-hour battery life. Color: Black.",
        category="mobile-accessories",
        price=18.00,  # Estimated total = 18 * 1.05 + 9.99 = $28.89 USD ≈ ₹2,398 INR
        brand="Sony",
        rating=4.5,
        stock=15,
        tags=["electronics", "audio", "headphones", "sony", "wireless"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=102,
        title="Apple AirPods Max",
        description="Over-ear active noise cancelling headphones in Space Gray finish.",
        category="mobile-accessories",
        price=499.00,  # Far above ₹2500 / ₹1000
        brand="Apple",
        rating=4.8,
        stock=5,
        tags=["audio", "headphones", "apple", "wireless"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=103,
        title="Generic Wired Earphones",
        description="3.5mm wired earphones with built-in microphone for mobile phones. No color specified.",
        category="mobile-accessories",
        price=5.00,  # Estimated total = 5 * 1.05 + 9.99 = $15.24 USD ≈ ₹1,265 INR
        brand="Generic",
        rating=3.2,
        stock=20,
        tags=["audio", "earphones", "wired"],
        availabilityStatus="In Stock",
    ),
    # Excluded accessories in same category (mobile-accessories)
    NormalizedProduct(
        id=104,
        title="iPhone 13 Silicone Protective Case",
        description="Soft touch black silicone protective case for Apple iPhone 13.",
        category="mobile-accessories",
        price=8.00,
        brand="Apple",
        rating=4.2,
        stock=30,
        tags=["accessories", "case", "iphone"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=105,
        title="Fast Qi Wireless Charger Stand",
        description="15W wireless charging stand compatible with black phones and headphones.",
        category="mobile-accessories",
        price=12.00,
        brand="Anker",
        rating=4.6,
        stock=40,
        tags=["charger", "wireless"],
        availabilityStatus="In Stock",
    ),
    # Smartphones
    NormalizedProduct(
        id=201,
        title="Samsung Galaxy A15 5G",
        description="Samsung smartphone with 6.5 inch display, 128GB storage, 50MP camera.",
        category="smartphones",
        price=140.00,  # Estimated total = 140 * 1.05 + 9.99 = $156.99 USD ≈ ₹13,030 INR <= ₹15,000
        brand="Samsung",
        rating=4.4,
        stock=25,
        tags=["smartphones", "samsung", "galaxy", "5g"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=202,
        title="Apple iPhone 15 Pro",
        description="Titanium design, A17 Pro chip, 48MP camera, 128GB.",
        category="smartphones",
        price=999.00,  # Way above ₹15,000
        brand="Apple",
        rating=4.9,
        stock=10,
        tags=["smartphones", "apple", "iphone"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=203,
        title="Samsung Galaxy S24 Ultra",
        description="Flagship smartphone with AI features and 200MP camera.",
        category="smartphones",
        price=1199.00,  # Far above ₹15,000
        brand="Samsung",
        rating=4.9,
        stock=8,
        tags=["smartphones", "samsung", "flagship"],
        availabilityStatus="In Stock",
    ),
    # Shoes
    NormalizedProduct(
        id=301,
        title="Nike Air Zoom Running Shoes",
        description="Lightweight red sports shoes designed for running and athletic training.",
        category="mens-shoes",
        price=12.00,  # Estimated total = 12 * 1.05 + 9.99 = $22.59 USD ≈ ₹1,875 INR <= ₹2,000
        brand="Nike",
        rating=4.7,
        stock=18,
        tags=["shoes", "running", "sports", "red"],
        availabilityStatus="In Stock",
    ),
    NormalizedProduct(
        id=302,
        title="Puma White Casual Sneakers",
        description="Comfortable white lifestyle sneakers for daily wear.",
        category="mens-shoes",
        price=14.00,
        brand="Puma",
        rating=4.3,
        stock=12,
        tags=["shoes", "casual", "sneakers", "white"],
        availabilityStatus="In Stock",
    ),
]


@pytest.fixture(autouse=True)
def mock_product_service_calls():
    """Mock product_service listing and searching to return our controlled mock catalogue."""
    with patch("app.services.recommendation_service.product_service") as mock_ps:
        mock_ps.list_products = AsyncMock(return_value=ProductListResponse(
            products=MOCK_PRODUCTS, total=len(MOCK_PRODUCTS), skip=0, limit=100
        ))
        mock_ps.search_products = AsyncMock(return_value=ProductListResponse(
            products=MOCK_PRODUCTS, total=len(MOCK_PRODUCTS), skip=0, limit=100
        ))
        yield mock_ps


@pytest.mark.asyncio
async def test_1_black_headphones_under_1000_inr():
    """
    Test 1: 'Black headphones under 1000' (₹1000 INR).
    ₹1000 INR = ~$12.05 USD.
    Products exceeding budget cannot be FULL MATCH.
    Phone cases, chargers, mounts must be excluded.
    If color is not verified in API data, must not claim it is black.
    """
    intent = {
        "category": "Headphones",
        "max_budget": 1000.0,
        "currency": "INR",
        "features": ["Black color"],
        "brand": [],
        "request": "i need headphones under 1000 in black color",
    }
    res = await recommendation_service.get_recommendations(intent)

    # 1. Phone cases and chargers must NOT be recommended as matching category
    for rec in res.recommendations:
        assert rec.product["id"] not in (104, 105), "Accessories must not be recommended as headphones"

    # 2. Expensive headphones ($499 Apple AirPods Max) must be EXCLUDED due to budget
    airpods = next((r for r in res.recommendations if r.product["id"] == 102), None)
    if airpods:
        assert airpods.match_tier == MatchTier.EXCLUDED
        assert airpods.is_fully_matching is False
        assert any("exceeds" in m.lower() for m in airpods.mismatch_reasons)

    # 3. Sony WH-CH520 costs ~₹2,398 INR which exceeds ₹1000 INR budget -> cannot be FULL MATCH
    sony = next((r for r in res.recommendations if r.product["id"] == 101), None)
    if sony:
        assert sony.is_fully_matching is False
        assert sony.match_tier == MatchTier.EXCLUDED

    # 4. Total full matches should be 0 because no headphone in mock catalogue is under ₹1000 with fees
    assert res.full_matches_count == 0


@pytest.mark.asyncio
async def test_2_sony_headphones_under_2500_inr():
    """
    Test 2: 'Sony headphones under 2500' (₹2500 INR = ~$30.12 USD).
    Sony WH-CH520 ($18 + fees = $28.89 ≈ ₹2,398 INR) is within budget.
    Apple headphones and generic headphones must NOT be recommended as matching Sony brand.
    """
    intent = {
        "category": "Headphones",
        "brand": ["Sony"],
        "max_budget": 2500.0,
        "currency": "INR",
        "features": [],
        "request": "I want Sony headphones under 2500",
    }
    res = await recommendation_service.get_recommendations(intent)

    # Sony headphone must be a FULL MATCH
    sony = next((r for r in res.recommendations if r.product["id"] == 101), None)
    assert sony is not None
    assert sony.match_tier == MatchTier.FULL_MATCH
    assert sony.is_fully_matching is True
    assert sony.breakdown.brand_match_score == 15.0
    assert sony.breakdown.category_match_score == 30.0
    assert sony.breakdown.price_suitability_score == 20.0

    # Apple AirPods Max must be EXCLUDED (Brand and Budget mismatch)
    apple = next((r for r in res.recommendations if r.product["id"] == 102), None)
    if apple:
        assert apple.match_tier == MatchTier.EXCLUDED
        assert apple.is_fully_matching is False

    # Generic earphones must be EXCLUDED or marked as Brand Mismatch
    generic = next((r for r in res.recommendations if r.product["id"] == 103), None)
    if generic:
        assert generic.match_tier == MatchTier.EXCLUDED
        assert generic.breakdown.brand_match_score == 0.0


@pytest.mark.asyncio
async def test_3_wireless_headphones_under_3000_inr():
    """
    Test 3: 'Wireless headphones under 3000' (₹3000 INR = ~$36.14 USD).
    Sony WH-CH520 (wireless, ₹2,398 INR) is within budget and verified wireless.
    Generic wired earphones must NOT receive wireless feature match.
    """
    intent = {
        "category": "Headphones",
        "max_budget": 3000.0,
        "currency": "INR",
        "features": ["Wireless"],
        "brand": [],
        "request": "Wireless headphones under 3000",
    }
    res = await recommendation_service.get_recommendations(intent)

    sony = next((r for r in res.recommendations if r.product["id"] == 101), None)
    assert sony is not None
    assert sony.match_tier == MatchTier.FULL_MATCH
    assert sony.is_fully_matching is True
    assert sony.breakdown.feature_match_score == 25.0

    # Wired earphones (id 103) must NOT match wireless
    wired = next((r for r in res.recommendations if r.product["id"] == 103), None)
    if wired:
        assert wired.is_fully_matching is False
        assert wired.breakdown.feature_match_score == 0.0


@pytest.mark.asyncio
async def test_4_samsung_smartphone_under_15000_inr():
    """
    Test 4: 'Samsung smartphone under 15000' (₹15000 INR = ~$180.72 USD).
    Samsung Galaxy A15 ($140 + fees = $156.99 ≈ ₹13,030 INR) fits budget.
    Apple iPhone and Samsung Galaxy S24 Ultra ($1199) must be EXCLUDED.
    Phone cases and chargers must NEVER be recommended.
    """
    intent = {
        "category": "Smartphones",
        "brand": ["Samsung"],
        "max_budget": 15000.0,
        "currency": "INR",
        "features": [],
        "request": "Samsung smartphone under 15000",
    }
    res = await recommendation_service.get_recommendations(intent)

    # Samsung A15 must be top recommendation and FULL MATCH
    a15 = next((r for r in res.recommendations if r.product["id"] == 201), None)
    assert a15 is not None
    assert a15.match_tier == MatchTier.FULL_MATCH
    assert a15.is_fully_matching is True

    # iPhone 15 Pro (id 202) must be EXCLUDED
    iphone = next((r for r in res.recommendations if r.product["id"] == 202), None)
    if iphone:
        assert iphone.match_tier == MatchTier.EXCLUDED

    # S24 Ultra (id 203) exceeds budget -> EXCLUDED
    s24 = next((r for r in res.recommendations if r.product["id"] == 203), None)
    if s24:
        assert s24.match_tier == MatchTier.EXCLUDED

    # No phone cases (id 104) in smartphone results
    for rec in res.recommendations:
        assert rec.product["id"] != 104, "Phone case must not be in smartphone recommendations"


@pytest.mark.asyncio
async def test_5_red_sports_shoes_under_2000_inr():
    """
    Test 5: 'Red sports shoes under 2000' (₹2000 INR = ~$24.10 USD).
    Nike Air Zoom (id 301, red, sports, running, ~$22.59 ≈ ₹1,875 INR) is a FULL MATCH.
    Puma White Casual Sneakers (id 302, white, not red, casual) cannot be FULL MATCH.
    """
    intent = {
        "category": "Shoes",
        "max_budget": 2000.0,
        "currency": "INR",
        "features": ["Red color", "Sports"],
        "brand": [],
        "request": "Red sports shoes under 2000",
    }
    res = await recommendation_service.get_recommendations(intent)

    nike = next((r for r in res.recommendations if r.product["id"] == 301), None)
    assert nike is not None
    assert nike.match_tier == MatchTier.FULL_MATCH
    assert nike.is_fully_matching is True
    assert nike.breakdown.feature_match_score > 0

    puma = next((r for r in res.recommendations if r.product["id"] == 302), None)
    if puma:
        assert puma.is_fully_matching is False
        assert puma.match_tier != MatchTier.FULL_MATCH


@pytest.mark.asyncio
async def test_6_headphones_under_500_inr_no_false_matches():
    """
    Test 6: 'Headphones under 500' (₹500 INR = ~$6.02 USD).
    No product in the mock catalogue can meet ₹500 with $9.99 shipping fees.
    Must return 0 false full matches!
    """
    intent = {
        "category": "Headphones",
        "max_budget": 500.0,
        "currency": "INR",
        "features": [],
        "brand": [],
        "request": "Headphones under 500",
    }
    res = await recommendation_service.get_recommendations(intent)

    assert res.full_matches_count == 0
    # Every returned product must be marked EXCLUDED due to budget
    for r in res.recommendations:
        assert r.match_tier == MatchTier.EXCLUDED
        assert r.is_fully_matching is False


@pytest.mark.asyncio
async def test_7_black_headphones_when_api_lacks_color_info():
    """
    Test 7: 'Black headphones under 1000' when API has no color information.
    Must mark as NOT VERIFIED.
    Must exclude from full match.
    Must not invent or guess color.
    """
    unverified_headphone = NormalizedProduct(
        id=999,
        title="PureSound Studio Monitor Headphones",
        description="Professional studio monitoring headphones with 40mm drivers.",  # NO color mentioned
        category="mobile-accessories",
        price=10.00,
        brand="PureSound",
        rating=4.5,
        stock=10,
        tags=["audio", "headphones", "studio"],
        availabilityStatus="In Stock",
    )

    with patch("app.services.recommendation_service.product_service") as mock_ps:
        mock_ps.list_products = AsyncMock(return_value=ProductListResponse(
            products=[unverified_headphone], total=1, skip=0, limit=10
        ))
        mock_ps.search_products = AsyncMock(return_value=ProductListResponse(
            products=[unverified_headphone], total=1, skip=0, limit=10
        ))

        intent = {
            "category": "Headphones",
            "max_budget": 5000.0,  # Generous budget
            "currency": "INR",
            "features": ["Black color"],
            "brand": [],
            "request": "Black headphones under 5000",
        }
        res = await recommendation_service.get_recommendations(intent)

        assert res.total == 1
        item = res.recommendations[0]
        # Must be NOT VERIFIED, NOT FULL MATCH
        assert item.match_tier == MatchTier.NOT_VERIFIED
        assert item.is_fully_matching is False
        assert "Black color" in item.unverified_features
        color_req = next((m for m in item.analysis["matches"] if "color" in m["requested"].lower()), None)
        assert color_req is not None
        assert color_req["status"] == "Not verified"
        assert color_req["verified"] is False


@pytest.mark.asyncio
async def test_8_change_shopping_request_discards_previous():
    """
    Test 8: Change shopping request from 'headphones' to 'smartphone'.
    Verify that subsequent recommendation call uses the new intent and discards previous results.
    """
    # 1. Search for Headphones
    intent_headphones = {
        "category": "Headphones",
        "max_budget": 5000.0,
        "currency": "INR",
        "request": "I need headphones",
    }
    res_headphones = await recommendation_service.get_recommendations(intent_headphones)
    # Headphone results should only contain headphones (no smartphones)
    for rec in res_headphones.recommendations:
        if rec.match_tier in (MatchTier.FULL_MATCH, MatchTier.NOT_VERIFIED):
            assert "phone" not in rec.product["category"] or "accessories" in rec.product["category"]

    # 2. Search for Smartphone
    intent_smartphones = {
        "category": "Smartphones",
        "brand": ["Samsung"],
        "max_budget": 20000.0,
        "currency": "INR",
        "request": "I want a Samsung smartphone",
    }
    res_smartphones = await recommendation_service.get_recommendations(intent_smartphones)

    # Top recommendation must be a Samsung smartphone, NOT any previous headphone
    assert res_smartphones.total > 0
    top_item = res_smartphones.recommendations[0]
    assert top_item.product["category"] == "smartphones"
    assert "samsung" in top_item.product["brand"].lower()
    assert top_item.match_tier == MatchTier.FULL_MATCH

