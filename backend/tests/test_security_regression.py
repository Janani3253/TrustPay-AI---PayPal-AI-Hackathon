from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app
from app.schemas.intent import (
    BudgetSpecification,
    StructuredIntentExtraction,
)
from app.schemas.product import NormalizedProduct, ProductListResponse

MOCK_USER = {"id": 1, "name": "Regression Tester", "email": "tester@trustpay.ai"}


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_full_regression_pipeline_coexistence(auth_client: AsyncClient):
    """
    Verify that existing API endpoints (platforms, products, intent)
    and new security endpoint function harmoniously without regressions.
    """
    # 1. Platform listing
    resp_plat = await auth_client.get("/api/platforms")
    assert resp_plat.status_code == 200
    assert any(p["id"] == "dummyjson" for p in resp_plat.json())

    # 2. Product listing
    mock_prod = NormalizedProduct(
        id=99,
        title="Eco Laptop Stand",
        description="Recycled aluminum laptop riser.",
        price=Decimal("45.00"),
        category="office",
        brand="EcoStand",
        platform_id="dummyjson",
    )
    with patch(
        "app.routers.products.product_service.list_products",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = ProductListResponse(
            products=[mock_prod], total=1, skip=0, limit=20
        )
        resp_prod = await auth_client.get("/api/products")
        assert resp_prod.status_code == 200
        assert len(resp_prod.json()["products"]) == 1

    # 3. Intent parsing
    mock_intent = StructuredIntentExtraction(
        product_type="stand",
        product_category="office",
        search_keywords=["laptop stand"],
        budget=BudgetSpecification(amount=Decimal("50.00"), currency="USD", evidence="under $50"),
    )
    with patch.object(settings, "GEMINI_API_KEY", "real-valid-key-1234567890"):
        with patch(
            "app.services.intent_service.gemini_service.extract_shopping_intent",
            new_callable=AsyncMock,
        ) as mock_ai:
            mock_ai.return_value = mock_intent
            resp_intent = await auth_client.post(
                "/api/intent/parse",
                json={
                    "request": "Need a laptop stand under $50.",
                    "maximumBudget": 50.0,
                    "currency": "USD",
                    "trustedSellersOnly": True,
                    "platformId": "dummyjson",
                },
            )
            assert resp_intent.status_code == 200
            assert resp_intent.json()["structured_intent"]["product_type"] == "stand"

    # 4. Security inspection
    with patch(
        "app.routers.security.product_service.get_product_details",
        new_callable=AsyncMock,
    ) as mock_details:
        mock_details.return_value = mock_prod
        resp_sec = await auth_client.post(
            "/api/security/analyze-product",
            json={
                "product_id": 99,
                "provider": "DEMO",
                "analysis_mode": "RULE_BASED_ONLY",
            },
        )
        assert resp_sec.status_code == 200
        assert resp_sec.json()["risk_level"] == "SAFE"
        assert resp_sec.json()["detected"] is False
