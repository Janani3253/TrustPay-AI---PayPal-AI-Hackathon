from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.schemas.product import NormalizedProduct, ProductCategory, ProductListResponse


MOCK_PRODUCT = NormalizedProduct(
    id=1,
    title="Essence Mascara Lash Princess",
    description="Cruelty-free mascara.",
    category="beauty",
    price=9.99,
    rating=4.94,
    brand="Essence",
    sku="RCH45Q1A",
    weight=2.0,
    availabilityStatus="In Stock",
    thumbnail="https://cdn.dummyjson.com/products/images/beauty/1/thumbnail.png",
    images=["https://cdn.dummyjson.com/products/images/beauty/1/1.png"],
    provider="DEMO",
    currency="USD",
)

MOCK_CATEGORIES = [
    ProductCategory(slug="beauty", name="Beauty", url="https://dummyjson.com/products/category/beauty"),
    ProductCategory(slug="smartphones", name="Smartphones", url="https://dummyjson.com/products/category/smartphones"),
]


@pytest.mark.asyncio
async def test_list_products_endpoint():
    """Verify GET /api/products returns normalized envelope matching ProductApiListResponse."""
    mock_response = ProductListResponse(
        products=[MOCK_PRODUCT],
        total=1,
        skip=0,
        limit=200,
    )
    with patch("app.routers.products.product_service.list_products", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/products?limit=20&skip=0")
            assert response.status_code == 200
            data = response.json()

            assert "products" in data
            assert data["total"] == 1
            assert data["skip"] == 0
            assert data["limit"] == 200

            prod = data["products"][0]
            # Verify exact frontend contract fields
            assert prod["id"] == 1
            assert prod["title"] == "Essence Mascara Lash Princess"
            assert prod["price"] == 9.99
            assert prod["category"] == "beauty"
            assert prod["thumbnail"] != ""
            assert isinstance(prod["images"], list)


@pytest.mark.asyncio
async def test_list_products_invalid_pagination():
    """Verify limit > 200 or skip < 0 returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get("/api/products?limit=250")
        assert res1.status_code == 422

        res2 = await client.get("/api/products?skip=-1")
        assert res2.status_code == 422


@pytest.mark.asyncio
async def test_search_products_endpoint():
    """Verify GET /api/products/search executes keyword search."""
    mock_response = ProductListResponse(
        products=[MOCK_PRODUCT],
        total=1,
        skip=0,
        limit=20,
    )
    with patch("app.routers.products.product_service.search_products", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/products/search?q=mascara")
            assert response.status_code == 200
            data = response.json()
            assert len(data["products"]) == 1
            assert data["products"][0]["title"] == "Essence Mascara Lash Princess"


@pytest.mark.asyncio
async def test_search_products_empty_query():
    """Verify searching with empty query returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/products/search?q=%20%20")
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_categories_endpoint():
    """Verify GET /api/products/categories returns ProductCategory list."""
    with patch("app.routers.products.product_service.list_categories", new_callable=AsyncMock) as mock_cats:
        mock_cats.return_value = MOCK_CATEGORIES

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/products/categories")
            assert response.status_code == 200
            cats = response.json()
            assert len(cats) == 2
            assert cats[0]["slug"] == "beauty"
            assert cats[0]["name"] == "Beauty"
            assert cats[0]["url"] != ""


@pytest.mark.asyncio
async def test_get_product_details_success():
    """Verify GET /api/products/{id} returns single normalized product."""
    with patch("app.routers.products.product_service.get_product_details", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MOCK_PRODUCT

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/products/1")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 1
            assert data["title"] == "Essence Mascara Lash Princess"
            assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_product_details_not_found():
    """Verify non-existent product ID returns 404."""
    from app.providers.exceptions import ProductNotFoundError
    with patch("app.routers.products.product_service.get_product_details", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ProductNotFoundError(9999)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/products/9999")
            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_get_product_details_invalid_id():
    """Verify non-numeric or <= 0 product ID returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.get("/api/products/0")
        assert res1.status_code == 422

        res2 = await client.get("/api/products/not-a-number")
        assert res2.status_code == 422


@pytest.mark.asyncio
async def test_recommendations_endpoint_backward_compatibility():
    """Verify recommendations endpoint functions with new product service."""
    from unittest.mock import MagicMock
    from app.core.dependencies import get_current_user

    mock_user = {"id": 1, "name": "Test User", "email": "test@example.com"}
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_response = ProductListResponse(
        products=[MOCK_PRODUCT],
        total=1,
        skip=0,
        limit=200,
    )
    with patch("app.main.add_audit"):
        with patch("app.services.product_service.product_service.search_products", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_response

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Test POST
                payload = {
                    "intent": {
                        "request": "Essence Mascara under $50",
                        "maximumBudget": 50.0,
                        "currency": "USD",
                        "requirements": [],
                    }
                }
                res = await client.post("/api/recommendations/search", json=payload)
                assert res.status_code == 200
                data = res.json()
                assert "recommendations" in data
                assert len(data["recommendations"]) == 1
                rec = data["recommendations"][0]
                assert "product" in rec
                assert "analysis" in rec
                assert rec["analysis"]["budgetMatched"] is True

                # Test GET backward compatibility
                res_get = await client.get("/api/recommendations/search?request=Essence&maximumBudget=50")
                assert res_get.status_code == 200
                data_get = res_get.json()
                assert "recommendations" in data_get

    app.dependency_overrides.clear()
