from typing import List, Optional
from fastapi import APIRouter, Depends
from app.core.dependencies import get_optional_current_user
from app.models.user import User
from app.schemas.product import ShoppingPlatformResponse
from app.services.product_service import product_service

router = APIRouter(prefix="/api/platforms", tags=["Platforms"])


@router.get(
    "",
    response_model=List[ShoppingPlatformResponse],
    summary="List supported shopping platforms",
    description=(
        "Returns available shopping platforms. DummyJSON is active as a demo catalogue; "
        "marketplace platforms (Amazon, Flipkart, Myntra) are unconfigured in this phase."
    ),
)
async def list_platforms(
    user: Optional[User] = Depends(get_optional_current_user),
) -> List[ShoppingPlatformResponse]:
    """Retrieve supported platforms and integration status."""
    return await product_service.get_platforms()

