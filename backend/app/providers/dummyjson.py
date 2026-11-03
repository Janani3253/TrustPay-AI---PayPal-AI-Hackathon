import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx

from app.core.config import settings
from app.providers.base import BaseProductProvider
from app.providers.exceptions import (
    InvalidPaginationError,
    InvalidProviderResponseError,
    InvalidSearchQueryError,
    ProductNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.schemas.product import (
    NormalizedProduct,
    ProductCategory,
    ProductDimensions,
    ProductListResponse,
    ShoppingPlatformResponse,
)

logger = logging.getLogger(__name__)


class DummyJSONProvider(BaseProductProvider):
    """
    Asynchronous Product Provider adapter for DummyJSON (https://dummyjson.com).
    Provides resilient HTTP client operations with connection pooling, bounded retries,
    and rigorous schema normalization.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self._base_url = (base_url or settings.DUMMYJSON_BASE_URL).rstrip("/")
        self._timeout = timeout or settings.PRODUCT_REQUEST_TIMEOUT_SECONDS
        self._custom_client = client is not None
        if client:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                transport=transport,
                headers={"Accept": "application/json", "User-Agent": "TrustPay-AI/1.0"},
            )

    @property
    def provider_id(self) -> str:
        return "dummyjson"

    @property
    def display_name(self) -> str:
        return "DummyJSON Demo Store"

    @property
    def is_supported(self) -> bool:
        return settings.DUMMYJSON_ENABLED

    @property
    def is_demo(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return "Catalogue browsing and product details are provided by DummyJSON."

    @property
    def status(self) -> str:
        return "ACTIVE" if self.is_supported else "NOT_CONFIGURED"

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute an HTTP request with a bounded exponential backoff retry strategy.
        Retries transient connection drops, timeouts, and upstream 5xx errors.
        Never retries 4xx client errors.
        """
        max_attempts = max(1, settings.PRODUCT_RETRY_ATTEMPTS + 1)
        last_exception: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                response = await self._client.request(
                    method=method,
                    url=path,
                    params=params,
                )

                # Check HTTP status
                if response.status_code == 404:
                    # 404 is an expected non-retryable response
                    raise ProductNotFoundError(params.get("id") if params else path)

                if 400 <= response.status_code < 500:
                    # 4xx client errors: do not retry
                    logger.warning(
                        "DummyJSON client error: status=%d path=%s response=%s",
                        response.status_code,
                        path,
                        response.text[:200],
                    )
                    raise InvalidProviderResponseError(
                        f"Product provider rejected request with status {response.status_code}."
                    )

                if response.status_code >= 500:
                    # 5xx server errors are retryable
                    if attempt < max_attempts - 1:
                        backoff = 0.05 * (2 ** attempt)
                        logger.warning(
                            "DummyJSON upstream 5xx error (%d) on %s, retrying in %.2fs (attempt %d/%d)",
                            response.status_code,
                            path,
                            backoff,
                            attempt + 1,
                            max_attempts,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise ProviderUnavailableError(
                        f"Product catalogue returned upstream server error {response.status_code}."
                    )

                # Parse JSON
                try:
                    return response.json()
                except ValueError as json_err:
                    raise InvalidProviderResponseError(
                        "Product provider returned an invalid JSON response."
                    ) from json_err

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as timeout_err:
                last_exception = timeout_err
                if attempt < max_attempts - 1:
                    backoff = 0.05 * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise ProviderTimeoutError(
                    "Product catalogue request timed out after multiple attempts."
                ) from timeout_err

            except (httpx.ConnectError, httpx.NetworkError) as net_err:
                last_exception = net_err
                if attempt < max_attempts - 1:
                    backoff = 0.05 * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise ProviderUnavailableError(
                    "Unable to connect to product catalogue service."
                ) from net_err

            except (ProductNotFoundError, InvalidProviderResponseError, ProviderUnavailableError):
                raise

            except Exception as unhandled:
                logger.error("Unexpected error contacting DummyJSON: %s", str(unhandled))
                raise ProviderUnavailableError("An error occurred while contacting the product catalogue.") from unhandled

        raise ProviderUnavailableError(f"Product catalogue request failed after {max_attempts} attempts.")

    def _normalize_item(self, raw: Dict[str, Any]) -> NormalizedProduct:
        """Map raw DummyJSON dictionary into NormalizedProduct schema."""
        raw_dims = raw.get("dimensions")
        dims = None
        if isinstance(raw_dims, dict):
            dims = ProductDimensions(
                width=float(raw_dims.get("width") or 0.0),
                height=float(raw_dims.get("height") or 0.0),
                depth=float(raw_dims.get("depth") or 0.0),
            )

        raw_id = raw.get("id")
        try:
            prod_id = int(raw_id)
        except (ValueError, TypeError):
            prod_id = 0

        raw_price = raw.get("price")
        try:
            price = float(raw_price) if raw_price is not None else 0.0
        except (ValueError, TypeError):
            price = 0.0

        raw_rating = raw.get("rating")
        try:
            rating = float(raw_rating) if raw_rating is not None else 0.0
        except (ValueError, TypeError):
            rating = 0.0

        images = raw.get("images")
        if not isinstance(images, list):
            images = []

        thumbnail = str(raw.get("thumbnail") or (images[0] if images else ""))

        return NormalizedProduct(
            id=prod_id,
            title=str(raw.get("title") or "Unknown Product"),
            description=str(raw.get("description") or ""),
            category=str(raw.get("category") or ""),
            price=price,
            rating=rating,
            brand=str(raw.get("brand")) if raw.get("brand") else None,
            sku=str(raw.get("sku")) if raw.get("sku") else None,
            weight=float(raw["weight"]) if raw.get("weight") is not None and isinstance(raw["weight"], (int, float)) else None,
            dimensions=dims,
            tags=[str(t) for t in raw.get("tags", []) if t],
            availabilityStatus=str(raw.get("availabilityStatus") or "In Stock"),
            thumbnail=thumbnail,
            images=[str(img) for img in images if img],
            provider="DEMO",
            external_product_id=str(raw_id),
            currency="USD",
            seller_name=None,
            seller_verified=False,
            stock=int(raw["stock"]) if raw.get("stock") is not None and isinstance(raw["stock"], (int, float)) else None,
        )

    async def get_products(
        self,
        limit: int = 200,
        skip: int = 0,
        category: Optional[str] = None,
    ) -> ProductListResponse:
        """Fetch list of products from DummyJSON."""
        if not (1 <= limit <= settings.PRODUCT_MAX_PAGE_SIZE):
            raise InvalidPaginationError(f"limit must be between 1 and {settings.PRODUCT_MAX_PAGE_SIZE}.")
        if skip < 0:
            raise InvalidPaginationError("skip must be greater than or equal to 0.")

        params = {"limit": limit, "skip": skip}

        if category and category.strip():
            safe_cat = quote(category.strip().lower(), safe="")
            path = f"/products/category/{safe_cat}"
        else:
            path = "/products"

        data = await self._request_with_retry("GET", path, params=params)

        if not isinstance(data, dict):
            raise InvalidProviderResponseError("Upstream product catalogue returned invalid payload.")

        raw_products = data.get("products", [])
        normalized = [self._normalize_item(p) for p in raw_products if isinstance(p, dict)]
        total = int(data.get("total", len(normalized)))
        skip_val = int(data.get("skip", skip))
        limit_val = int(data.get("limit", limit))

        return ProductListResponse(
            products=normalized,
            total=total,
            skip=skip_val,
            limit=limit_val,
        )

    async def search_products(
        self,
        query: str,
        limit: int = 200,
        skip: int = 0,
    ) -> ProductListResponse:
        """Search products by keyword."""
        q = (query or "").strip()
        if not q:
            raise InvalidSearchQueryError("Search query must not be empty.")
        if not (1 <= limit <= settings.PRODUCT_MAX_PAGE_SIZE):
            raise InvalidPaginationError(f"limit must be between 1 and {settings.PRODUCT_MAX_PAGE_SIZE}.")
        if skip < 0:
            raise InvalidPaginationError("skip must be greater than or equal to 0.")

        params = {"q": q, "limit": limit, "skip": skip}
        data = await self._request_with_retry("GET", "/products/search", params=params)

        if not isinstance(data, dict):
            raise InvalidProviderResponseError("Upstream search returned invalid payload.")

        raw_products = data.get("products", [])
        normalized = [self._normalize_item(p) for p in raw_products if isinstance(p, dict)]
        total = int(data.get("total", len(normalized)))
        skip_val = int(data.get("skip", skip))
        limit_val = int(data.get("limit", limit))

        return ProductListResponse(
            products=normalized,
            total=total,
            skip=skip_val,
            limit=limit_val,
        )

    async def get_product_by_id(self, product_id: int | str) -> NormalizedProduct:
        """Fetch and normalize product details for a given ID."""
        try:
            numeric_id = int(product_id)
            if numeric_id <= 0:
                raise ValueError("Must be positive")
        except (ValueError, TypeError) as err:
            raise ProductNotFoundError(product_id) from err

        data = await self._request_with_retry("GET", f"/products/{numeric_id}", params={"id": numeric_id})

        if not isinstance(data, dict) or data.get("id") != numeric_id:
            raise InvalidProviderResponseError("Upstream product payload is invalid or mismatched.")

        return self._normalize_item(data)

    async def get_categories(self) -> List[ProductCategory]:
        """Fetch all product categories."""
        data = await self._request_with_retry("GET", "/products/categories")

        if not isinstance(data, list):
            raise InvalidProviderResponseError("Upstream categories payload must be a list.")

        categories: List[ProductCategory] = []
        for item in data:
            if isinstance(item, str):
                slug = item.strip().lower()
                name = slug.replace("-", " ").title()
                url = f"{self._base_url}/products/category/{quote(slug, safe='')}"
                categories.append(ProductCategory(slug=slug, name=name, url=url))
            elif isinstance(item, dict):
                slug = str(item.get("slug") or "").strip().lower()
                name = str(item.get("name") or slug.replace("-", " ").title())
                url = str(item.get("url") or f"{self._base_url}/products/category/{quote(slug, safe='')}")
                if slug:
                    categories.append(ProductCategory(slug=slug, name=name, url=url))

        # Sort categories by display name for consistent presentation
        categories.sort(key=lambda c: c.name)
        return categories

    async def get_provider_status(self) -> ShoppingPlatformResponse:
        """Return platform status matching frontend contract."""
        return ShoppingPlatformResponse(
            id="dummyjson",
            name="DummyJSON Demo Store",
            supported=self.is_supported,
            demo_only=True,
            description="Catalogue browsing and product details are provided by DummyJSON.",
            connected=self.is_supported,
            status=self.status,
        )

    async def close(self) -> None:
        """Close HTTP client session."""
        if not self._custom_client and not self._client.is_closed:
            await self._client.aclose()

