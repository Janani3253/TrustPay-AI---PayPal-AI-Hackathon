from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.schemas.product import NormalizedProduct, ProductCategory, ProductListResponse, ShoppingPlatformResponse


class BaseProductProvider(ABC):
    """
    Abstract Base Class defining the standard interface for external product providers.
    Every provider (e.g. DummyJSON, future Amazon/Flipkart) must implement these asynchronous methods.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Machine identifier for provider (e.g., 'dummyjson', 'amazon')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name for provider."""
        pass

    @property
    @abstractmethod
    def is_supported(self) -> bool:
        """Whether this provider can currently be selected for active shopping."""
        pass

    @property
    @abstractmethod
    def is_demo(self) -> bool:
        """Whether this provider represents a demo/mock catalogue."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the platform status."""
        pass

    @property
    @abstractmethod
    def status(self) -> str:
        """Operational status string: 'ACTIVE', 'NOT_CONFIGURED', 'UNAVAILABLE'."""
        pass

    @abstractmethod
    async def get_products(
        self,
        limit: int = 200,
        skip: int = 0,
        category: Optional[str] = None,
    ) -> ProductListResponse:
        """Retrieve paginated products, optionally filtered by category."""
        pass

    @abstractmethod
    async def search_products(
        self,
        query: str,
        limit: int = 200,
        skip: int = 0,
    ) -> ProductListResponse:
        """Search products by keyword."""
        pass

    @abstractmethod
    async def get_product_by_id(self, product_id: int | str) -> NormalizedProduct:
        """Retrieve a single normalized product by its ID."""
        pass

    @abstractmethod
    async def get_categories(self) -> List[ProductCategory]:
        """Retrieve all available product categories."""
        pass

    @abstractmethod
    async def get_provider_status(self) -> ShoppingPlatformResponse:
        """Return platform status matching the frontend ShoppingPlatform schema."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP and network resources."""
        pass

