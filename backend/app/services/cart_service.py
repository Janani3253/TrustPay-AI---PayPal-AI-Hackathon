from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.audit import add_audit
from app.core.config import settings
from app.core.database import get_session_factory
from app.database import connect, initialize_database
from app.models.cart import Cart, CartItem
from app.repositories.cart_repository import CartRepository
from app.security.injection_detector import injection_detector
from app.services.product_service import product_service
from app.services.prompt_injection_service import prompt_injection_service

logger = logging.getLogger(__name__)

FEE_SHIPPING = Decimal("9.99")
FEE_TAX_RATE = Decimal("0.05")


class CartService:
    """
    Authoritative Shopping Cart Service managing cart lifecycle, trusted product snapshots,
    exact Decimal calculations, prompt injection security metadata, and legacy SQLite mirroring.
    """

    @staticmethod
    def calculate_totals(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate cart financial totals using exact Decimal arithmetic.
        """
        subtotal = Decimal("0.00")
        currencies = set()

        for item in items:
            product = item.get("product", {})
            price = Decimal(str(product.get("price", "0.00")))
            qty = Decimal(str(item.get("quantity", 1)))
            subtotal += price * qty

            curr = product.get("currency", "USD")
            if curr:
                currencies.add(curr)

        if len(currencies) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mixed currencies in shopping cart are not permitted.",
            )

        currency = next(iter(currencies)) if currencies else "USD"
        shipping = FEE_SHIPPING if subtotal > Decimal("0.00") else Decimal("0.00")
        tax = (subtotal * FEE_TAX_RATE).quantize(Decimal("0.01"))
        total = subtotal + shipping + tax

        return {
            "subtotal": float(subtotal),
            "shipping": float(shipping),
            "tax": float(tax),
            "total": float(total),
            "currency": currency,
        }

    @staticmethod
    def _mirror_to_sqlite_add(user_id: int, product_id: int, quantity: int) -> None:
        """Mirror add operation to legacy SQLite database for backward compatibility."""
        def _do_insert(c):
            c.execute(
                "INSERT OR IGNORE INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, f"User {user_id}", f"user{user_id}@trustpay.ai", "hash", "2026-01-01T00:00:00Z"),
            )
            c.execute(
                """INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + excluded.quantity""",
                (user_id, product_id, quantity),
            )

        try:
            with connect() as conn:
                _do_insert(conn)
        except Exception:
            try:
                initialize_database()
                with connect() as conn:
                    _do_insert(conn)
            except Exception as exc:
                logger.debug("SQLite cart mirror add failed: %s", exc)

    @staticmethod
    def _mirror_to_sqlite_update(user_id: int, product_id: int, quantity: int) -> None:
        """Mirror quantity update to legacy SQLite database."""
        try:
            with connect() as conn:
                conn.execute(
                    "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
                    (quantity, user_id, product_id),
                )
        except Exception:
            try:
                initialize_database()
                with connect() as conn:
                    conn.execute(
                        "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
                        (quantity, user_id, product_id),
                    )
            except Exception as exc:
                logger.debug("SQLite cart mirror update failed: %s", exc)

    @staticmethod
    def _mirror_to_sqlite_delete(user_id: int, product_id: int) -> None:
        """Mirror item deletion to legacy SQLite database."""
        try:
            with connect() as conn:
                conn.execute(
                    "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                )
        except Exception:
            try:
                initialize_database()
                with connect() as conn:
                    conn.execute(
                        "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
                        (user_id, product_id),
                    )
            except Exception as exc:
                logger.debug("SQLite cart mirror delete failed: %s", exc)

    @staticmethod
    def _mirror_to_sqlite_clear(user_id: int) -> None:
        """Mirror cart clearing to legacy SQLite database."""
        try:
            with connect() as conn:
                conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        except Exception:
            try:
                initialize_database()
                with connect() as conn:
                    conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            except Exception as exc:
                logger.debug("SQLite cart mirror clear failed: %s", exc)

    async def get_cart(self, user_id: int) -> Dict[str, Any]:
        """Retrieve authoritative cart representation compatible with frontend."""
        if settings.is_postgres_configured:
            factory = get_session_factory()
            if factory:
                async with factory() as session:
                    cart = await CartRepository.get_or_create_cart(session, user_id)
                    items_stmt = select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
                    items = (await session.execute(items_stmt)).scalars().all()
                    items_data = []
                    for it in items:
                        items_data.append({
                            "product": it.product_snapshot,
                            "quantity": it.quantity,
                            "content_hash": it.content_hash,
                            "security_risk": it.security_risk_level,
                            "security_status": it.security_analysis_status,
                        })
                    totals = self.calculate_totals(items_data)
                    return {
                        "cart_id": cart.id,
                        "version": cart.version,
                        "items": items_data,
                        "totals": totals,
                    }

        # Fallback to SQLite prototype store
        try:
            with connect() as conn:
                rows = conn.execute(
                    "SELECT product_id, quantity FROM cart_items WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
        except Exception:
            initialize_database()
            with connect() as conn:
                rows = conn.execute(
                    "SELECT product_id, quantity FROM cart_items WHERE user_id = ?",
                    (user_id,),
                ).fetchall()

        items = []
        for r in rows:
            prod_id = r["product_id"]
            qty = r["quantity"]
            try:
                prod = await product_service.get_product_details(prod_id)
                prod_dict = prod.model_dump() if hasattr(prod, "model_dump") else dict(prod)
            except Exception:
                prod_dict = {"id": prod_id, "title": f"Product {prod_id}", "price": 0.0, "currency": "USD"}
            content_hash = prompt_injection_service.compute_content_hash(prod_dict)
            findings, risk_level, _ = injection_detector.scan_product_dict(prod_dict)
            items.append({
                "product": prod_dict,
                "quantity": qty,
                "content_hash": content_hash,
                "security_risk": risk_level.value,
                "security_status": "COMPLETE",
            })

        totals = self.calculate_totals(items)
        return {"items": items, "totals": totals, "version": 1}

    async def add_item(
        self,
        user_id: int,
        product_id: int,
        quantity: int = 1,
        provider: str = "DEMO",
    ) -> Dict[str, Any]:
        """
        Add product to cart using authoritative backend product lookup,
        attaching security scan results and product snapshot.
        """
        if quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Quantity must be greater than zero.",
            )

        # 1. Fetch genuine product metadata from provider (NEVER trust client price)
        product = await product_service.get_product_details(product_id=product_id, platform_id=provider)
        product_dict = product.model_dump() if hasattr(product, "model_dump") else dict(product)
        product_dict["provider"] = provider

        unit_price = Decimal(str(product_dict.get("price", "0.00")))
        currency = str(product_dict.get("currency", "USD"))

        # 2. Canonical content hash & deterministic security evaluation
        content_hash = prompt_injection_service.compute_content_hash(product_dict)
        findings, risk_level, _ = injection_detector.scan_product_dict(product_dict)
        findings_json = [f.model_dump() for f in findings]

        # 3. Save to PostgreSQL if configured
        if settings.is_postgres_configured:
            factory = get_session_factory()
            if factory:
                async with factory() as session:
                    async with session.begin():
                        cart = await CartRepository.get_or_create_cart(session, user_id)
                        await CartRepository.add_item(
                            session=session,
                            cart=cart,
                            provider=provider,
                            external_product_id=product_id,
                            quantity=quantity,
                            unit_price=unit_price,
                            currency=currency,
                            product_snapshot=product_dict,
                            content_hash=content_hash,
                            security_risk_level=risk_level.value,
                            security_analysis_status="COMPLETE",
                            security_findings=findings_json,
                        )

        # 4. Mirror to SQLite to ensure legacy compatibility
        self._mirror_to_sqlite_add(user_id, product_id, quantity)

        # 5. Audit event
        add_audit(
            user_id=user_id,
            event_type="CART_ITEM_ADDED",
            description=f"Added product {product_id} ({quantity}x) to cart. Security risk: {risk_level.value}.",
        )

        return await self.get_cart(user_id)

    async def update_quantity(
        self,
        user_id: int,
        product_id: int,
        quantity: int,
        provider: str = "DEMO",
    ) -> Dict[str, Any]:
        """Update item quantity in cart."""
        if quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Quantity must be greater than zero.",
            )

        updated = False
        if settings.is_postgres_configured:
            factory = get_session_factory()
            if factory:
                async with factory() as session:
                    async with session.begin():
                        cart = await CartRepository.get_or_create_cart(session, user_id)
                        item = await CartRepository.update_quantity(
                            session=session,
                            cart=cart,
                            external_product_id=product_id,
                            quantity=quantity,
                            provider=provider,
                        )
                        if item is not None:
                            updated = True

        # SQLite update
        with connect() as conn:
            cursor = conn.execute(
                "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
                (quantity, user_id, product_id),
            )
            if cursor.rowcount > 0:
                updated = True

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart item was not found.",
            )

        add_audit(
            user_id=user_id,
            event_type="CART_ITEM_UPDATED",
            description=f"Updated product {product_id} quantity to {quantity}.",
        )
        return await self.get_cart(user_id)

    async def remove_item(
        self,
        user_id: int,
        product_id: int,
        provider: str = "DEMO",
    ) -> None:
        """Remove item from cart."""
        if settings.is_postgres_configured:
            factory = get_session_factory()
            if factory:
                async with factory() as session:
                    async with session.begin():
                        cart = await CartRepository.get_or_create_cart(session, user_id)
                        await CartRepository.remove_item(
                            session=session,
                            cart=cart,
                            external_product_id=product_id,
                            provider=provider,
                        )

        self._mirror_to_sqlite_delete(user_id, product_id)
        add_audit(
            user_id=user_id,
            event_type="CART_ITEM_REMOVED",
            description=f"Removed product {product_id} from cart.",
        )

    async def clear_cart(self, user_id: int) -> None:
        """Clear all items from customer cart."""
        if settings.is_postgres_configured:
            factory = get_session_factory()
            if factory:
                async with factory() as session:
                    async with session.begin():
                        cart = await CartRepository.get_or_create_cart(session, user_id)
                        await CartRepository.clear_cart(session, cart)

        self._mirror_to_sqlite_clear(user_id)
        add_audit(
            user_id=user_id,
            event_type="CART_CLEARED",
            description="Cleared all items from cart.",
        )


cart_service = CartService()
