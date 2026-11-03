"""FastAPI router for Order creation and management."""

from typing import Any, Dict
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user
from app.schemas.order import OrderCreateRequest, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/orders", tags=["Orders"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
async def create_order(
    payload: OrderCreateRequest,
    user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a verified/draft order from the current shopping cart."""
    user_id = _extract_user_id(user)
    return await OrderService.create_order(
        user_id=user_id,
        intent=payload.intent,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve an existing order by ID."""
    user_id = _extract_user_id(user)
    return await OrderService.get_order(
        order_id=order_id,
        user_id=user_id,
    )
