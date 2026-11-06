from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.core.dependencies import get_optional_current_user
from app.models.user import User
from app.providers.exceptions import (
    InvalidPaginationError,
    InvalidProductIdError,
    InvalidSearchQueryError,
    ProductNotFoundError,
    ProductProviderException,
)
from app.schemas.product import (
    NormalizedProduct,
    ProductCategory,
    ProductListResponse,
)
from app.services.product_service import product_service

router = APIRouter(prefix="/api/products", tags=["Products"])


def _handle_provider_error(err: Exception) -> None:
    """Map internal provider exceptions to appropriate HTTPExceptions."""
    if isinstance(err, ProductProviderException):
        raise HTTPException(status_code=err.status_code, detail=err.message)
    if isinstance(err, HTTPException):
        raise err
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The product catalogue service is currently unavailable.",
    )


@router.get(
    "/categories",
    response_model=List[ProductCategory],
    summary="List product categories",
    description="Retrieve all available product categories from the upstream provider.",
)
async def list_categories(
    platform: Optional[str] = Query(None, description="Optional platform filter (e.g. dummyjson)"),
    user: Optional[User] = Depends(get_optional_current_user),
) -> List[ProductCategory]:
    """Retrieve all categories supported by the platform."""
    try:
        return await product_service.list_categories(platform_id=platform)
    except Exception as err:
        _handle_provider_error(err)


@router.get(
    "/search",
    response_model=ProductListResponse,
    summary="Search products by keyword",
    description="Search active product catalog by query string with pagination.",
)
async def search_products(
    q: str = Query(..., min_length=1, description="Keyword search query"),
    limit: int = Query(20, ge=1, le=200, description="Items per page"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    platform: Optional[str] = Query(None, description="Platform identifier"),
    user: Optional[User] = Depends(get_optional_current_user),
) -> ProductListResponse:
    """Execute product keyword search against the upstream catalog."""
    clean_q = (q or "").strip()
    if not clean_q:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query must not be empty.",
        )
    try:
        return await product_service.search_products(
            query=clean_q,
            limit=limit,
            skip=skip,
            platform_id=platform,
        )
    except Exception as err:
        _handle_provider_error(err)


@router.get(
    "",
    response_model=ProductListResponse,
    summary="List and filter catalog products",
    description="Retrieve products with optional keyword, category filtering, and pagination.",
)
async def list_products(
    q: Optional[str] = Query(None, description="Optional keyword search"),
    category: Optional[str] = Query(None, description="Optional category slug filter"),
    limit: int = Query(200, ge=1, le=200, description="Items per page"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    platform: Optional[str] = Query(None, description="Platform identifier"),
    user: Optional[User] = Depends(get_optional_current_user),
) -> ProductListResponse:
    """Retrieve paginated products matching query or category filters."""
    if not (1 <= limit <= 200):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit must be between 1 and 200.",
        )
    if skip < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="skip must be greater than or equal to 0.",
        )
    try:
        return await product_service.list_products(
            query=q,
            category=category,
            limit=limit,
            skip=skip,
            platform_id=platform,
        )
    except Exception as err:
        _handle_provider_error(err)


@router.get(
    "/{product_id}",
    response_model=NormalizedProduct,
    summary="Get single product details",
    description="Retrieve full normalized details for an individual product by ID.",
)
async def get_product_details(
    product_id: int,
    platform: Optional[str] = Query(None, description="Platform identifier"),
    user: Optional[User] = Depends(get_optional_current_user),
) -> NormalizedProduct:
    """Retrieve normalized product details by integer ID."""
    if product_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product ID must be a positive integer.",
        )
    try:
        return await product_service.get_product_details(
            product_id=product_id,
            platform_id=platform,
        )
    except Exception as err:
        _handle_provider_error(err)

