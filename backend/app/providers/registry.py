from typing import Dict, List, Optional
from app.providers.amazon import AmazonProvider
from app.providers.base import BaseProductProvider
from app.providers.dummyjson import DummyJSONProvider
from app.providers.exceptions import UnsupportedProviderError
from app.providers.flipkart import FlipkartProvider
from app.providers.myntra import MyntraProvider
from app.schemas.product import ShoppingPlatformResponse


class ProviderRegistry:
    """
    Central registry managing available product provider instances,
    platform lookups, and lifecycle.
    """

    def __init__(
        self,
        dummyjson_provider: Optional[BaseProductProvider] = None,
    ):
        self._dummyjson = dummyjson_provider or DummyJSONProvider()
        self._amazon = AmazonProvider()
        self._flipkart = FlipkartProvider()
        self._myntra = MyntraProvider()

        # Map aliases to providers
        self._providers: Dict[str, BaseProductProvider] = {
            "dummyjson": self._dummyjson,
            "demo": self._dummyjson,
            "dummy": self._dummyjson,
            "amazon": self._amazon,
            "flipkart": self._flipkart,
            "myntra": self._myntra,
        }

        # Ordered list for /api/platforms representation
        self._platform_order: List[BaseProductProvider] = [
            self._dummyjson,
            self._amazon,
            self._flipkart,
            self._myntra,
        ]

    def get_provider(self, platform_id: Optional[str] = None) -> BaseProductProvider:
        """
        Retrieve provider instance by identifier. Defaults to DummyJSON if omitted.
        Raises UnsupportedProviderError for unrecognized platform IDs.
        """
        if not platform_id:
            return self._dummyjson

        norm_id = platform_id.strip().lower()
        provider = self._providers.get(norm_id)
        if not provider:
            raise UnsupportedProviderError(platform_id)
        return provider

    async def list_platforms(self) -> List[ShoppingPlatformResponse]:
        """Return platform status for all registered shopping sources."""
        statuses = []
        for p in self._platform_order:
            statuses.append(await p.get_provider_status())
        return statuses

    async def close_all(self) -> None:
        """Close all registered provider network connections."""
        for p in self._platform_order:
            await p.close()


# Global default registry instance
provider_registry = ProviderRegistry()

