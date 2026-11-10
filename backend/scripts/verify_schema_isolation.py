import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings
from app.core.database import normalize_database_url

DB_URL = normalize_database_url(settings.DATABASE_URL)

async def run_simulation():
    print("=" * 70)
    print("STARTING COMPLETE STITCHMATE + TRUSTPAY_AI ISOLATION TEST")
    print("=" * 70)

    engine = create_async_engine(DB_URL)

    # Step 1: Simulate existing StitchMate database in 'public'
    print("\n[Step 1] Simulating StitchMate existing database in 'public'...")
    async with engine.begin() as conn:
        # Create StitchMate tables in public
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.stitchmate_clients (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                measurement_notes TEXT
            );
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.stitchmate_garments (
                id SERIAL PRIMARY KEY,
                client_id INT REFERENCES public.stitchmate_clients(id),
                garment_type VARCHAR(50),
                status VARCHAR(30)
            );
        """))
        # Insert StitchMate sample data
        await conn.execute(text("DELETE FROM public.stitchmate_garments;"))
        await conn.execute(text("DELETE FROM public.stitchmate_clients;"))
        await conn.execute(text("""
            INSERT INTO public.stitchmate_clients (id, name, measurement_notes)
            VALUES (1, 'Alice Smith (StitchMate Client)', 'Waist: 28in, Inseam: 32in');
        """))
        await conn.execute(text("""
            INSERT INTO public.stitchmate_garments (id, client_id, garment_type, status)
            VALUES (1, 1, 'Custom Suit', 'In Production');
        """))
        # Set a StitchMate version in public.alembic_version
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS public.alembic_version (
                version_num VARCHAR(32) PRIMARY KEY
            );
        """))
        await conn.execute(text("DELETE FROM public.alembic_version;"))
        await conn.execute(text("INSERT INTO public.alembic_version (version_num) VALUES ('stitchmate_rev_999');"))

    print("  -> Created public.stitchmate_clients (1 row)")
    print("  -> Created public.stitchmate_garments (1 row)")
    print("  -> Created public.alembic_version with version 'stitchmate_rev_999'")

    # Step 2: Clean slate for trustpay_ai schema to test Alembic migration from scratch
    print("\n[Step 2] Resetting 'trustpay_ai' schema to test clean deployment...")
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS trustpay_ai CASCADE;"))
        print("  -> Cleaned 'trustpay_ai' schema (DROP SCHEMA CASCADE)")

    # Step 3: Run Alembic migrations for TrustPay AI
    print("\n[Step 3] Executing TrustPay AI Alembic migrations (upgrade head)...")
    alembic_ini_path = str(BASE_DIR / "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)
    # alembic upgrade runs synchronously via run_migrations_online which handles async engine
    try:
        command.upgrade(alembic_cfg, "head")
        print("  -> Alembic upgrade head completed successfully!")
    except Exception as e:
        print(f"  -> Alembic upgrade error: {e}")
        raise

    # Step 4: Verify Schema Isolation
    print("\n[Step 4] Verifying schema contents and isolation...")
    async with engine.connect() as conn:
        # Check StitchMate data in public
        sm_client = (await conn.execute(text("SELECT name FROM public.stitchmate_clients WHERE id = 1;"))).scalar()
        sm_garment = (await conn.execute(text("SELECT garment_type, status FROM public.stitchmate_garments WHERE id = 1;"))).fetchone()
        sm_version = (await conn.execute(text("SELECT version_num FROM public.alembic_version;"))).scalar()

        print(f"  -> StitchMate Client: {sm_client} (INTACT)")
        print(f"  -> StitchMate Garment: {sm_garment} (INTACT)")
        print(f"  -> StitchMate Alembic Version: {sm_version} (UNTOUCHED: {sm_version == 'stitchmate_rev_999'})")

        assert sm_client == "Alice Smith (StitchMate Client)", "StitchMate data corrupted!"
        assert sm_version == "stitchmate_rev_999", "StitchMate alembic_version corrupted!"

        # Check TrustPay AI alembic version in trustpay_ai schema
        tp_version = (await conn.execute(text("SELECT version_num FROM trustpay_ai.alembic_version;"))).scalar()
        print(f"  -> TrustPay AI Alembic Version: {tp_version} (in trustpay_ai.alembic_version)")
        assert tp_version == "0005_transactions_audit", f"Unexpected TrustPay version: {tp_version}"

        # Check TrustPay AI tables
        tp_tables_res = await conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'trustpay_ai' AND table_name != 'alembic_version'
            ORDER BY table_name;
        """))
        tp_tables = [row[0] for row in tp_tables_res.fetchall()]
        print(f"  -> TrustPay AI Tables in 'trustpay_ai': {tp_tables}")
        expected_tables = ["approvals", "audit_events", "auth_sessions", "cart_items", "carts", "orders", "transactions", "users"]
        assert tp_tables == expected_tables, f"Missing tables: {set(expected_tables) - set(tp_tables)}"

        # Verify that NO trustpay tables exist in public (other than old ones if any)
        # Check that stitchmate tables do NOT exist in trustpay_ai
        tp_has_sm = (await conn.execute(text("""
            SELECT count(*) FROM information_schema.tables 
            WHERE table_schema = 'trustpay_ai' AND table_name LIKE 'stitchmate%';
        """))).scalar()
        assert tp_has_sm == 0, "StitchMate tables leaked into trustpay_ai schema!"

        # Step 5: Test application ORM operations
        print("\n[Step 5] Testing TrustPay AI runtime ORM operations in 'trustpay_ai'...")
        from app.models.user import User
        from app.models.cart import Cart
        from app.core.database import get_session_factory
        from sqlalchemy import select

        factory = get_session_factory()
        async with factory() as session:
            # Create a user
            test_user = User(
                name="Test TrustPay Customer",
                email="test_customer@trustpay.internal",
                password_hash="mock_hash_for_testing_isolation",
                role="customer",
                is_active=True,
            )
            session.add(test_user)
            await session.commit()
            await session.refresh(test_user)
            print(f"  -> Created User ID: {test_user.id} in trustpay_ai.users")

            # Create a cart for user
            user_cart = Cart(user_id=test_user.id, currency="USD")
            session.add(user_cart)
            await session.commit()
            await session.refresh(user_cart)
            print(f"  -> Created Cart ID: {user_cart.id} in trustpay_ai.carts")

            # Query back
            stmt = select(User).where(User.email == "test_customer@trustpay.internal")
            res_user = (await session.execute(stmt)).scalar_one_or_none()
            assert res_user is not None, "Failed to retrieve user from trustpay_ai schema!"
            print(f"  -> Verified ORM query retrieved user: {res_user.email}")

        # Verify raw SQL confirms data is in trustpay_ai and NOT in public
        async with engine.connect() as conn:
            tp_count = (await conn.execute(text("SELECT count(*) FROM trustpay_ai.users;"))).scalar()
            print(f"  -> trustpay_ai.users count: {tp_count}")
            assert tp_count == 1, "User was not saved to trustpay_ai.users!"

            # Verify StitchMate tables remain pristine
            sm_count = (await conn.execute(text("SELECT count(*) FROM public.stitchmate_clients;"))).scalar()
            print(f"  -> public.stitchmate_clients count: {sm_count} (Pristine)")
            assert sm_count == 1, "StitchMate table was modified!"

            # Step 6: Clean up simulation tables from public
            print("\n[Step 6] Cleaning up simulation tables from public schema...")
            await conn.execute(text("DROP TABLE IF EXISTS public.stitchmate_garments CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS public.stitchmate_clients CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS public.alembic_version CASCADE;"))
            print("  -> Cleaned up simulation tables in public schema.")

    print("\n" + "=" * 70)
    print("ALL VERIFICATIONS PASSED: 100% SAFE AND ISOLATED!")
    print("=" * 70)
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_simulation())
