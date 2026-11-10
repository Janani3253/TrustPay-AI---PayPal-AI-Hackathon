from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app
from app.schemas.intent import (
    BudgetSpecification,
    MandatorySpecification,
    PurchaseIntentResponse,
    PurchaseRequirement,
    StructuredIntentExtraction,
)
from app.schemas.product import NormalizedProduct, ProductListResponse


MOCK_USER = {"id": 1, "name": "Test User", "email": "test@example.com"}


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_intent_parse_success(auth_client: AsyncClient):
    """Verify POST /api/intent/parse returns contract compatible with frontend PurchaseIntent."""
    mock_extracted = StructuredIntentExtraction(
        product_type="laptop",
        product_category="laptops",
        search_keywords=["laptop", "16GB RAM"],
        budget=BudgetSpecification(amount=Decimal("800.00"), currency="USD", evidence="under $800"),
        mandatory_specifications=[
            MandatorySpecification(name="RAM", operator="GTE", value="16", unit="GB", evidence="16GB RAM"),
        ],
    )

    with patch.object(settings, "GEMINI_API_KEY", "valid_key_12345"):
        with patch("app.services.intent_service.gemini_service.extract_shopping_intent", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = mock_extracted

            payload = {
                "request": "I need a laptop under $800 with 16GB RAM.",
                "maximumBudget": 800.0,
                "currency": "USD",
                "category": "laptops",
                "trustedSellersOnly": True,
                "platformId": "dummyjson",
            }

            res = await auth_client.post("/api/intent/parse", json=payload)
            assert res.status_code == 200
            data = res.json()

            # Verify exact frontend contract fields
            assert data["request"] == payload["request"]
            assert data["category"] == "laptops"
            assert data["maximumBudget"] == 800.0
            assert data["currency"] == "USD"
            assert data["trustedSellersOnly"] is True
            assert data["platformId"] == "dummyjson"
            assert isinstance(data["requirements"], list)
            assert len(data["requirements"]) == 1
            assert data["requirements"][0]["name"] == "RAM"
            assert data["requirements"][0]["value"] == "16 GB"

            # Verify AI metadata
            assert data["extraction_method"] == "GEMINI"
            assert data["status"] == "READY_FOR_REVIEW"


@pytest.mark.asyncio
async def test_api_intent_parse_unconfigured(auth_client: AsyncClient):
    """Verify POST /api/intent/parse returns 503 when GEMINI_API_KEY is not configured."""
    with patch.object(settings, "GEMINI_API_KEY", None):
        payload = {
            "request": "I need a laptop under $800.",
            "maximumBudget": 800.0,
            "currency": "USD",
            "category": "laptops",
            "trustedSellersOnly": True,
            "platformId": "dummyjson",
        }
        res = await auth_client.post("/api/intent/parse", json=payload)
        assert res.status_code == 503
        data = res.json()
        assert "not configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_api_intent_parse_unsupported_platform(auth_client: AsyncClient):
    """Verify unsupported platformId returns 400 Bad Request."""
    payload = {
        "request": "I need a laptop.",
        "maximumBudget": 1000.0,
        "currency": "USD",
        "category": "laptops",
        "trustedSellersOnly": True,
        "platformId": "amazon",
    }
    res = await auth_client.post("/api/intent/parse", json=payload)
    assert res.status_code == 400
    assert "DummyJSON" in res.json()["detail"]


@pytest.mark.asyncio
async def test_api_intent_recommendations_compatibility(auth_client: AsyncClient):
    """Verify parsed intent can be passed directly to /api/recommendations/search."""
    mock_extracted = StructuredIntentExtraction(
        product_type="laptop",
        product_category="laptops",
        budget=BudgetSpecification(amount=Decimal("1200.00"), currency="USD", evidence="below $1200"),
    )

    mock_product = NormalizedProduct(
        id=78,
        title="Apple MacBook Pro 14 Inch",
        description="Laptop with M-series chip.",
        category="laptops",
        price=1099.99,
        rating=4.8,
        currency="USD",
        provider="DEMO",
    )

    with patch.object(settings, "GEMINI_API_KEY", "valid_key_12345"):
        with patch("app.services.intent_service.gemini_service.extract_shopping_intent", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = mock_extracted

            # 1. Parse intent
            parse_payload = {
                "request": "I need an Apple MacBook laptop below $1200",
                "maximumBudget": 1200.0,
                "currency": "USD",
                "category": "laptops",
                "trustedSellersOnly": True,
                "platformId": "dummyjson",
            }
            parse_res = await auth_client.post("/api/intent/parse", json=parse_payload)
            assert parse_res.status_code == 200
            intent_data = parse_res.json()

            # 2. Pass parsed intent into recommendations
            with patch("app.services.product_service.product_service.list_products", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ProductListResponse(
                    products=[mock_product],
                    total=1,
                    skip=0,
                    limit=200,
                )

                rec_res = await auth_client.post("/api/recommendations/search", json={"intent": intent_data})
                assert rec_res.status_code == 200
                rec_data = rec_res.json()
                assert "recommendations" in rec_data
                assert len(rec_data["recommendations"]) == 1
                assert rec_data["recommendations"][0]["analysis"]["categoryMatched"] is True
                assert rec_data["recommendations"][0]["analysis"]["budgetMatched"] is True

