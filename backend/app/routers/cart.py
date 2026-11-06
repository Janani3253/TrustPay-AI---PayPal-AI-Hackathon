from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas import CartItemRequest, CartQuantityRequest
from app.services.cart_service import cart_service

router = APIRouter(prefix="/api/cart", tags=["Cart"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.get("", response_model=Dict[str, Any], summary="Get current shopping cart")
async def get_cart(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Retrieve the current user's authoritative shopping cart and totals."""
    user_id = _extract_user_id(user)
    return await cart_service.get_cart(user_id)


@router.post("/items", response_model=Dict[str, Any], summary="Add product to shopping cart")
async def add_cart_item(
    payload: CartItemRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Add a verified product to cart using authoritative backend product lookup."""
    user_id = _extract_user_id(user)
    return await cart_service.add_item(
        user_id=user_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
    )


@router.put("/items/{product_id}", response_model=Dict[str, Any], summary="Update cart item quantity")
async def update_cart_item(
    product_id: int,
    payload: CartQuantityRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update quantity of an existing item in cart."""
    user_id = _extract_user_id(user)
    return await cart_service.update_quantity(
        user_id=user_id,
        product_id=product_id,
        quantity=payload.quantity,
    )


@router.delete(
    "/items/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove product from cart",
)
async def delete_cart_item(
    product_id: int,
    user: User = Depends(get_current_user),
) -> None:
    """Remove a product from the shopping cart."""
    user_id = _extract_user_id(user)
    await cart_service.remove_item(user_id=user_id, product_id=product_id)


@router.delete(
    "/items",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear all cart items",
)
async def clear_cart_items(
    user: User = Depends(get_current_user),
) -> None:
    """Clear all products from shopping cart."""
    user_id = _extract_user_id(user)
    await cart_service.clear_cart(user_id)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear entire cart",
)
async def clear_cart(
    user: User = Depends(get_current_user),
) -> None:
    """Alternative clear cart route."""
    user_id = _extract_user_id(user)
    await cart_service.clear_cart(user_id)

