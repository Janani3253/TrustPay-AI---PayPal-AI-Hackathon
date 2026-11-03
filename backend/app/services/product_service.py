import logging
from typing import List, Optional
from app.core.cache import ProductCache, product_cache
from app.providers.base import BaseProductProvider
from app.providers.exceptions import InvalidSearchQueryError
from app.providers.registry import ProviderRegistry, provider_registry
from app.schemas.product import (
    NormalizedProduct,
    ProductCategory,
    ProductListResponse,
    ShoppingPlatformResponse,
)

logger = logging.getLogger(__name__)


class ProductService:
    """
    Service layer coordinating product provider operations,
    in-memory caching, search, and catalog queries.
    """

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        cache: Optional[ProductCache] = None,
    ):
        self._registry = registry or provider_registry
        self._cache = cache or product_cache

    def get_provider(self, platform_id: Optional[str] = None) -> BaseProductProvider:
        """Resolve product provider from registry."""
        return self._registry.get_provider(platform_id)

    async def list_products(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 200,
        skip: int = 0,
        platform_id: Optional[str] = None,
    ) -> ProductListResponse:
        """
        Retrieve catalog products with optional keyword and category filtering.
        Utilizes cache when available.
        """
        provider = self.get_provider(platform_id)
        cache_key = self._cache.make_list_key(
            provider=provider.provider_id,
            query=query,
            category=category,
            limit=limit,
            skip=skip,
        )

        cached_data = await self._cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        if query and query.strip():
            # If search query provided, use search upstream
            result = await provider.search_products(
                query=query.strip(),
                limit=limit,
                skip=skip,
            )
            # If category is also provided, filter locally if upstream search did not filter
            if category and category.strip():
                clean_cat = category.strip().lower()
                filtered = [p for p in result.products if p.category.lower() == clean_cat]
                result = ProductListResponse(
                    products=filtered,
                    total=len(filtered),
                    skip=result.skip,
                    limit=result.limit,
                )
        else:
            result = await provider.get_products(
                limit=limit,
                skip=skip,
                category=category.strip() if category else None,
            )

        # Store in cache
        await self._cache.set(cache_key, result)

        # Pre-warm individual product caches
        for p in result.products:
            prod_key = self._cache.make_product_key(provider.provider_id, p.id)
            await self._cache.set(prod_key, p)

        return result

    async def search_products(
        self,
        query: str,
        limit: int = 200,
        skip: int = 0,
        platform_id: Optional[str] = None,
    ) -> ProductListResponse:
        """Search products by keyword."""
        q = (query or "").strip()
        if not q:
            raise InvalidSearchQueryError("Search query must not be empty.")

        provider = self.get_provider(platform_id)
        cache_key = self._cache.make_list_key(
            provider=provider.provider_id,
            query=q,
            category=None,
            limit=limit,
            skip=skip,
        )

        cached_data = await self._cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        result = await provider.search_products(query=q, limit=limit, skip=skip)
        await self._cache.set(cache_key, result)

        for p in result.products:
            prod_key = self._cache.make_product_key(provider.provider_id, p.id)
            await self._cache.set(prod_key, p)

        return result

    async def get_product_details(
        self,
        product_id: int | str,
        platform_id: Optional[str] = None,
    ) -> NormalizedProduct:
        """Retrieve detailed product information by ID."""
        provider = self.get_provider(platform_id)
        cache_key = self._cache.make_product_key(provider.provider_id, product_id)

        cached_product = await self._cache.get(cache_key)
        if cached_product is not None:
            return cached_product

        product = await provider.get_product_by_id(product_id)
        await self._cache.set(cache_key, product)
        return product

    async def list_categories(
        self,
        platform_id: Optional[str] = None,
    ) -> List[ProductCategory]:
        """Retrieve all categories supported by the provider."""
        provider = self.get_provider(platform_id)
        cache_key = self._cache.make_category_key(provider.provider_id)

        cached_categories = await self._cache.get(cache_key)
        if cached_categories is not None:
            return cached_categories

        categories = await provider.get_categories()
        await self._cache.set(cache_key, categories, ttl=self._cache.category_ttl)
        return categories

    async def get_platforms(self) -> List[ShoppingPlatformResponse]:
        """Return status for all registered shopping platforms."""
        return await self._registry.list_platforms()

    async def close(self) -> None:
        """Release provider resources."""
        await self._registry.close_all()


# Global default product service
product_service = ProductService()

