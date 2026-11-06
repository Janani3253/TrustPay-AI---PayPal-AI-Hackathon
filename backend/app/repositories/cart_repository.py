from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartItem


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CartRepository:
    """PostgreSQL repository handling persistence and versioning of shopping carts."""

    @staticmethod
    async def get_or_create_cart(session: AsyncSession, user_id: int) -> Cart:
        """Retrieve the customer's active cart or create one if none exists."""
        stmt = (
            select(Cart)
            .where(Cart.user_id == user_id)
            .options(selectinload(Cart.items))
        )
        result = await session.execute(stmt)
        cart = result.scalar_one_or_none()

        if cart is None:
            cart = Cart(
                user_id=user_id,
                version=1,
                currency="USD",
                created_at=utc_now(),
                updated_at=utc_now(),
                items=[],
            )
            session.add(cart)
            await session.flush()

        return cart

    @staticmethod
    async def get_cart(session: AsyncSession, user_id: int) -> Optional[Cart]:
        """Retrieve active cart by user ID with all items loaded."""
        stmt = (
            select(Cart)
            .where(Cart.user_id == user_id)
            .options(selectinload(Cart.items))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def add_item(
        session: AsyncSession,
        cart: Cart,
        provider: str,
        external_product_id: int,
        quantity: int,
        unit_price: Decimal,
        currency: str,
        product_snapshot: Dict[str, Any],
        content_hash: str,
        security_risk_level: str = "SAFE",
        security_analysis_status: str = "COMPLETE",
        security_findings: Optional[List[Dict[str, Any]]] = None,
    ) -> CartItem:
        """Add a product item to cart or increment quantity if already present."""
        findings = security_findings or []
        stmt = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.provider == provider,
            CartItem.external_product_id == external_product_id,
        )
        existing_item = (await session.execute(stmt)).scalar_one_or_none()

        now = utc_now()
        if existing_item:
            existing_item.quantity += quantity
            existing_item.unit_price = unit_price
            existing_item.currency = currency
            existing_item.product_snapshot = product_snapshot
            existing_item.content_hash = content_hash
            existing_item.security_risk_level = security_risk_level
            existing_item.security_analysis_status = security_analysis_status
            existing_item.security_findings = findings
            existing_item.price_observed_at = now
            existing_item.updated_at = now
            target_item = existing_item
        else:
            new_item = CartItem(
                cart_id=cart.id,
                provider=provider,
                external_product_id=external_product_id,
                quantity=quantity,
                unit_price=unit_price,
                currency=currency,
                product_snapshot=product_snapshot,
                content_hash=content_hash,
                security_risk_level=security_risk_level,
                security_analysis_status=security_analysis_status,
                security_findings=findings,
                price_observed_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(new_item)
            target_item = new_item

        cart.version += 1
        cart.updated_at = now
        await session.flush()
        return target_item

    @staticmethod
    async def update_quantity(
        session: AsyncSession,
        cart: Cart,
        external_product_id: int,
        quantity: int,
        provider: str = "DEMO",
    ) -> Optional[CartItem]:
        """Update item quantity in cart."""
        stmt = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.provider == provider,
            CartItem.external_product_id == external_product_id,
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            return None

        now = utc_now()
        item.quantity = quantity
        item.updated_at = now
        cart.version += 1
        cart.updated_at = now
        await session.flush()
        return item

    @staticmethod
    async def remove_item(
        session: AsyncSession,
        cart: Cart,
        external_product_id: int,
        provider: str = "DEMO",
    ) -> bool:
        """Remove an item from cart."""
        stmt = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.provider == provider,
            CartItem.external_product_id == external_product_id,
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            return False

        await session.delete(item)
        cart.version += 1
        cart.updated_at = utc_now()
        await session.flush()
        return True

    @staticmethod
    async def clear_cart(session: AsyncSession, cart: Cart) -> None:
        """Remove all items from cart."""
        await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
        cart.version += 1
        cart.updated_at = utc_now()
        await session.flush()

