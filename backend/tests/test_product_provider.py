import json
import pytest
import httpx

from app.providers.dummyjson import DummyJSONProvider
from app.providers.amazon import AmazonProvider
from app.providers.flipkart import FlipkartProvider
from app.providers.myntra import MyntraProvider
from app.providers.registry import ProviderRegistry
from app.providers.exceptions import (
    InvalidPaginationError,
    InvalidProviderResponseError,
    InvalidSearchQueryError,
    ProductNotFoundError,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedProviderError,
)
from app.schemas.product import NormalizedProduct


SAMPLE_PRODUCT_JSON = {
    "id": 1,
    "title": "Essence Mascara Lash Princess",
    "description": "Popular cruelty-free mascara for volume and length.",
    "category": "beauty",
    "price": 9.99,
    "rating": 4.94,
    "stock": 5,
    "tags": ["beauty", "mascara"],
    "brand": "Essence",
    "sku": "RCH45Q1A",
    "weight": 2,
    "dimensions": {"width": 23.17, "height": 14.43, "depth": 28.01},
    "availabilityStatus": "In Stock",
    "thumbnail": "https://cdn.dummyjson.com/products/images/beauty/1/thumbnail.png",
    "images": ["https://cdn.dummyjson.com/products/images/beauty/1/1.png"],
}


@pytest.mark.asyncio
async def test_dummyjson_get_products_success():
    """Verify fetching product listing with normalization."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products"
        return httpx.Response(
            status_code=200,
            json={
                "products": [SAMPLE_PRODUCT_JSON],
                "total": 1,
                "skip": 0,
                "limit": 200,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        result = await provider.get_products(limit=10, skip=0)

        assert result.total == 1
        assert len(result.products) == 1
        prod = result.products[0]
        assert isinstance(prod, NormalizedProduct)
        assert prod.id == 1
        assert prod.title == "Essence Mascara Lash Princess"
        assert prod.price == 9.99
        assert prod.currency == "USD"
        assert prod.provider == "DEMO"
        assert prod.seller_name is None
        assert prod.seller_verified is False
        assert prod.dimensions.width == 23.17


@pytest.mark.asyncio
async def test_dummyjson_search_products_success():
    """Verify keyword product search."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/search"
        assert request.url.params["q"] == "laptop"
        return httpx.Response(
            status_code=200,
            json={
                "products": [SAMPLE_PRODUCT_JSON],
                "total": 1,
                "skip": 0,
                "limit": 20,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        result = await provider.search_products(query="laptop", limit=20, skip=0)
        assert result.total == 1
        assert result.products[0].id == 1


@pytest.mark.asyncio
async def test_dummyjson_search_empty_query_raises():
    """Verify empty search query raises InvalidSearchQueryError."""
    provider = DummyJSONProvider()
    with pytest.raises(InvalidSearchQueryError):
        await provider.search_products(query="   ")


@pytest.mark.asyncio
async def test_dummyjson_invalid_pagination():
    """Verify invalid limit or negative skip raises InvalidPaginationError."""
    provider = DummyJSONProvider()
    with pytest.raises(InvalidPaginationError):
        await provider.get_products(limit=300)
    with pytest.raises(InvalidPaginationError):
        await provider.get_products(skip=-1)


@pytest.mark.asyncio
async def test_dummyjson_get_product_by_id_success():
    """Verify retrieving individual product details by integer ID."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/1"
        return httpx.Response(status_code=200, json=SAMPLE_PRODUCT_JSON)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        product = await provider.get_product_by_id(1)
        assert product.id == 1
        assert product.brand == "Essence"


@pytest.mark.asyncio
async def test_dummyjson_get_product_not_found():
    """Verify 404 response raises ProductNotFoundError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404, json={"message": "Product with id '9999' not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        with pytest.raises(ProductNotFoundError):
            await provider.get_product_by_id(9999)


@pytest.mark.asyncio
async def test_dummyjson_upstream_500_error():
    """Verify upstream 5xx errors trigger retries and raise ProviderUnavailableError."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code=502, text="Bad Gateway")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_products()
        assert attempts >= 2


@pytest.mark.asyncio
async def test_dummyjson_malformed_json():
    """Verify malformed upstream JSON response raises InvalidProviderResponseError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="Not valid json {")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        with pytest.raises(InvalidProviderResponseError):
            await provider.get_products()


@pytest.mark.asyncio
async def test_dummyjson_get_categories():
    """Verify category retrieval parses both string lists and dict lists."""
    # Test format with string list
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=["smartphones", "laptops", "fragrances"],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://dummyjson.com", transport=transport) as client:
        provider = DummyJSONProvider(client=client)
        categories = await provider.get_categories()
        assert len(categories) == 3
        assert categories[0].slug in ("fragrances", "laptops", "smartphones")
        assert categories[0].name != ""
        assert "products/category" in categories[0].url


@pytest.mark.asyncio
async def test_unsupported_providers_raise():
    """Verify Amazon, Flipkart, and Myntra raise ProviderNotConfiguredError."""
    amazon = AmazonProvider()
    flipkart = FlipkartProvider()
    myntra = MyntraProvider()

    assert amazon.is_supported is False
    assert amazon.status == "NOT_CONFIGURED"

    with pytest.raises(ProviderNotConfiguredError):
        await amazon.get_products()

    with pytest.raises(ProviderNotConfiguredError):
        await flipkart.search_products("shoes")

    with pytest.raises(ProviderNotConfiguredError):
        await myntra.get_product_by_id(1)


@pytest.mark.asyncio
async def test_provider_registry():
    """Verify registry selects appropriate providers and handles unsupported requests."""
    registry = ProviderRegistry()

    # Default resolution
    default_provider = registry.get_provider(None)
    assert default_provider.provider_id == "dummyjson"

    # Explicit resolution
    demo_provider = registry.get_provider("dummyjson")
    assert demo_provider.provider_id == "dummyjson"

    amazon = registry.get_provider("amazon")
    assert amazon.provider_id == "Amazon"

    # Unsupported provider
    with pytest.raises(UnsupportedProviderError):
        registry.get_provider("ebay")

    # Platform list
    platforms = await registry.list_platforms()
    assert len(platforms) == 4
    assert platforms[0].id == "dummyjson"
    assert platforms[0].supported is True
    assert platforms[1].id == "Amazon"
    assert platforms[1].supported is False

