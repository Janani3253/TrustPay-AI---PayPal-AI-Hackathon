from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductDimensions(BaseModel):
    """Product physical dimensions."""
    model_config = ConfigDict(extra="ignore")

    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0


class ProductReview(BaseModel):
    """Customer review from upstream catalog."""
    model_config = ConfigDict(extra="ignore")

    rating: float = 0.0
    comment: str = ""
    date: Optional[str] = None
    reviewerName: Optional[str] = None
    reviewerEmail: Optional[str] = None


class NormalizedProduct(BaseModel):
    """
    Normalized product model matching the existing React frontend's ProductApiProduct contract.
    Preserves exact field names, integer ID, and types, while augmenting with provider metadata.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int = Field(description="Unique integer product identifier for frontend compatibility")
    title: str = Field(description="Product title")
    description: str = Field(default="", description="Product description")
    category: str = Field(default="", description="Product category slug")
    price: float = Field(description="Unit price in provider source currency")
    rating: float = Field(default=0.0, description="Average customer review rating")
    brand: Optional[str] = Field(default=None, description="Manufacturer brand name")
    sku: Optional[str] = Field(default=None, description="Stock keeping unit")
    weight: Optional[float] = Field(default=None, description="Product weight")
    dimensions: Optional[ProductDimensions] = Field(default=None, description="Dimensions")
    tags: List[str] = Field(default_factory=list, description="Associated search tags")
    availabilityStatus: Optional[str] = Field(
        default="In Stock",
        alias="availability_status",
        description="Availability status (In Stock, Low Stock, etc.)",
    )
    thumbnail: str = Field(default="", description="Primary thumbnail image URL")
    images: List[str] = Field(default_factory=list, description="Array of gallery image URLs")

    # Extra Normalized Enterprise Fields
    provider: str = Field(default="DEMO", description="Source provider identifier (DEMO, AMAZON, etc.)")
    external_product_id: Optional[str] = Field(default=None, description="Original upstream product ID")
    currency: str = Field(default="USD", description="Source currency code (DummyJSON uses USD)")
    seller_name: Optional[str] = Field(default=None, description="Seller identity (unknown for demo catalog)")
    seller_verified: bool = Field(default=False, description="Verification status of seller")
    stock: Optional[int] = Field(default=None, description="Current available inventory")

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: Any) -> float:
        """Ensure price is validated with Decimal precision and rounded to 2 decimal places."""
        try:
            d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return float(d)
        except Exception as err:
            raise ValueError(f"Invalid price value: {v}") from err

    @field_validator("id", mode="before")
    @classmethod
    def validate_id(cls, v: Any) -> int:
        """Ensure product ID can be parsed as an integer for frontend compatibility."""
        try:
            return int(v)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Product ID must be an integer: {v}") from err

    @field_validator("images", mode="before")
    @classmethod
    def validate_images(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(item) for item in v if item]
        return []


class ProductListResponse(BaseModel):
    """Envelope for paginated product list responses matching frontend ProductApiListResponse."""
    model_config = ConfigDict(extra="ignore")

    products: List[NormalizedProduct] = Field(default_factory=list, description="List of normalized products")
    total: int = Field(default=0, description="Total matching products in upstream catalogue")
    skip: int = Field(default=0, description="Pagination offset")
    limit: int = Field(default=200, description="Pagination page limit")


class ProductCategory(BaseModel):
    """Product category representation matching frontend ProductCategory interface."""
    model_config = ConfigDict(extra="ignore")

    slug: str = Field(description="URL-safe category slug")
    name: str = Field(description="Display name for category")
    url: str = Field(default="", description="Direct upstream category URL")


class ShoppingPlatformResponse(BaseModel):
    """Shopping platform status matching frontend ShoppingPlatform interface."""
    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Platform identifier (e.g. dummyjson, Amazon)")
    name: str = Field(description="Display name for shopping platform")
    supported: bool = Field(description="Whether the platform is supported for active shopping")
    demo_only: bool = Field(description="Whether the platform is a mock/demo catalogue")
    description: str = Field(description="Platform status or integration explanation")
    connected: Optional[bool] = Field(default=None, description="Connectivity status flag")
    status: Optional[str] = Field(default=None, description="Detailed status (ACTIVE, NOT_CONFIGURED)")

