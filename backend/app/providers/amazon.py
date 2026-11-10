from typing import List, Optional
from app.providers.base import BaseProductProvider
from app.providers.exceptions import ProviderNotConfiguredError
from app.schemas.product import (
    NormalizedProduct,
    ProductCategory,
    ProductListResponse,
    ShoppingPlatformResponse,
)


class AmazonProvider(BaseProductProvider):
    """
    Adapter for Amazon platform. Direct shopping integration is not currently configured.
    """

    @property
    def provider_id(self) -> str:
        return "Amazon"

    @property
    def display_name(self) -> str:
        return "Amazon"

    @property
    def is_supported(self) -> bool:
        return False

    @property
    def is_demo(self) -> bool:
        return False

    @property
    def description(self) -> str:
        return "Direct shopping integration is not configured for this platform."

    @property
    def status(self) -> str:
        return "NOT_CONFIGURED"

    async def get_products(
        self,
        limit: int = 200,
        skip: int = 0,
        category: Optional[str] = None,
    ) -> ProductListResponse:
        raise ProviderNotConfiguredError("Amazon")

    async def search_products(
        self,
        query: str,
        limit: int = 200,
        skip: int = 0,
    ) -> ProductListResponse:
        raise ProviderNotConfiguredError("Amazon")

    async def get_product_by_id(self, product_id: int | str) -> NormalizedProduct:
        raise ProviderNotConfiguredError("Amazon")

    async def get_categories(self) -> List[ProductCategory]:
        raise ProviderNotConfiguredError("Amazon")

    async def get_provider_status(self) -> ShoppingPlatformResponse:
        return ShoppingPlatformResponse(
            id=self.provider_id,
            name=self.display_name,
            supported=self.is_supported,
            demo_only=self.is_demo,
            description=self.description,
            connected=False,
            status=self.status,
        )

    async def close(self) -> None:
        pass

