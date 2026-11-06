"""
Legacy Cart Migration Utility
Safely inspects and migrates existing SQLite cart_items to PostgreSQL carts and cart_items.
Usage:
    python backend/scripts/migrate_legacy_cart.py --dry-run
    python backend/scripts/migrate_legacy_cart.py --apply
"""
import argparse
import asyncio
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

# Add backend directory to path
backend_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_path))

from app.core.config import settings
from app.core.database import get_session_factory
from app.models.cart import Cart, CartItem
from app.repositories.cart_repository import CartRepository
from app.security.injection_detector import injection_detector
from app.services.product_service import product_service
from app.services.prompt_injection_service import prompt_injection_service


def read_sqlite_cart_items(db_path: str) -> list[dict]:
    """Read cart_items from legacy SQLite database."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT user_id, product_id, quantity FROM cart_items").fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"Error reading SQLite cart items: {e}")
        return []
    finally:
        conn.close()


async def run_migration(apply_changes: bool = False) -> None:
    db_path = settings.TRUSTPAY_DATABASE_PATH
    print(f"Reading legacy cart items from: {db_path}")
    items = read_sqlite_cart_items(db_path)
    print(f"Found {len(items)} legacy cart items across users.")

    user_groups: dict[int, list[dict]] = {}
    for item in items:
        uid = item["user_id"]
        user_groups.setdefault(uid, []).append(item)

    print(f"Total distinct users with cart items: {len(user_groups)}")
    for uid, uitems in user_groups.items():
        print(f"  User {uid}: {len(uitems)} items -> {[(it['product_id'], it['quantity']) for it in uitems]}")

    if not apply_changes:
        print("\n[DRY RUN COMPLETE] To apply changes to PostgreSQL, pass --apply")
        return

    if not settings.is_postgres_configured:
        print("\n[ERROR] PostgreSQL is not configured in settings. Cannot apply migration.")
        return

    factory = get_session_factory()
    if not factory:
        print("\n[ERROR] Could not initialize PostgreSQL session factory.")
        return

    print("\nApplying migration to PostgreSQL...")
    async with factory() as session:
        async with session.begin():
            for uid, uitems in user_groups.items():
                cart = await CartRepository.get_or_create_cart(session, uid)
                for it in uitems:
                    pid = it["product_id"]
                    qty = it["quantity"]
                    try:
                        product = await product_service.get_product_details(pid)
                        product_dict = product.model_dump() if hasattr(product, "model_dump") else dict(product)
                        unit_price = Decimal(str(product_dict.get("price", "0.00")))
                        currency = str(product_dict.get("currency", "USD"))
                    except Exception:
                        product_dict = {"id": pid, "title": f"Product {pid}", "price": 0.0, "currency": "USD"}
                        unit_price = Decimal("0.00")
                        currency = "USD"

                    content_hash = prompt_injection_service.compute_content_hash(product_dict)
                    findings, risk_level, _ = injection_detector.scan_product_dict(product_dict)

                    await CartRepository.add_item(
                        session=session,
                        cart=cart,
                        provider="DEMO",
                        external_product_id=pid,
                        quantity=qty,
                        unit_price=unit_price,
                        currency=currency,
                        product_snapshot=product_dict,
                        content_hash=content_hash,
                        security_risk_level=risk_level.value,
                        security_analysis_status="COMPLETE",
                        security_findings=[f.model_dump() for f in findings],
                    )
    print("Migration successfully applied!")


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite cart items to PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Inspect items without applying.")
    parser.add_argument("--apply", action="store_true", default=False, help="Apply migration to PostgreSQL.")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Please specify either --dry-run or --apply")
        sys.exit(1)

    asyncio.run(run_migration(apply_changes=args.apply))


if __name__ == "__main__":
    main()
