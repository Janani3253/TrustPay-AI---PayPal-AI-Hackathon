#!/usr/bin/env python3
"""
Legacy SQLite to PostgreSQL User Migration Tool.
Transfers user accounts from SQLite trustpay.db into PostgreSQL users table,
preserving exact integer primary-key IDs and legacy PBKDF2 hashes.
"""

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, text
from app.core.config import settings
from app.core.database import get_async_engine, get_session_factory
from app.models.user import User


def mask_email(email: str) -> str:
    """Mask email for privacy in logs and reports."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:1]}***{local[-1:]}"
    return f"{masked_local}@{domain}"


def read_sqlite_users(sqlite_path: Path) -> List[Dict[str, Any]]:
    """Read existing user records from SQLite database in read-only mode."""
    if not sqlite_path.exists():
        return []

    connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.cursor()
        rows = cursor.execute("SELECT id, name, email, password_hash, created_at FROM users ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


async def inspect_postgres_users(session) -> Tuple[Dict[int, User], Dict[str, User]]:
    """Retrieve existing PostgreSQL users indexed by ID and normalized email."""
    stmt = select(User)
    result = await session.execute(stmt)
    users = result.scalars().all()
    by_id = {u.id: u for u in users}
    by_email = {u.email.lower(): u for u in users}
    return by_id, by_email


async def plan_migration(sqlite_path: Path) -> Dict[str, Any]:
    """Inspect source and destination, producing a detailed migration preview."""
    source_users = read_sqlite_users(sqlite_path)
    engine = get_async_engine()

    if engine is None or not settings.is_postgres_configured:
        return {
            "status": "postgres_not_configured",
            "source_count": len(source_users),
            "records": source_users,
        }

    factory = get_session_factory()
    if factory is None:
        return {
            "status": "postgres_session_failed",
            "source_count": len(source_users),
            "records": source_users,
        }

    async with factory() as session:
        pg_by_id, pg_by_email = await inspect_postgres_users(session)

    to_insert: List[Dict[str, Any]] = []
    already_matching: List[Dict[str, Any]] = []
    id_conflicts: List[Dict[str, Any]] = []
    email_conflicts: List[Dict[str, Any]] = []

    for row in source_users:
        uid = row["id"]
        email = User.normalize_email(row["email"])

        existing_by_id = pg_by_id.get(uid)
        existing_by_email = pg_by_email.get(email)

        if existing_by_id and existing_by_email and existing_by_id.id == existing_by_email.id:
            already_matching.append({"id": uid, "masked_email": mask_email(email)})
        elif existing_by_id:
            id_conflicts.append({
                "id": uid,
                "sqlite_email": mask_email(email),
                "postgres_email": mask_email(existing_by_id.email),
            })
        elif existing_by_email:
            email_conflicts.append({
                "sqlite_id": uid,
                "postgres_id": existing_by_email.id,
                "masked_email": mask_email(email),
            })
        else:
            to_insert.append(row)

    return {
        "status": "ready",
        "source_count": len(source_users),
        "to_insert_count": len(to_insert),
        "already_matching_count": len(already_matching),
        "id_conflicts_count": len(id_conflicts),
        "email_conflicts_count": len(email_conflicts),
        "to_insert": to_insert,
        "already_matching": already_matching,
        "id_conflicts": id_conflicts,
        "email_conflicts": email_conflicts,
    }


async def apply_migration(plan: Dict[str, Any]) -> int:
    """Execute the user migration into PostgreSQL."""
    if plan.get("status") != "ready":
        raise RuntimeError("Cannot apply migration: PostgreSQL is not configured or ready.")

    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Session factory unavailable.")

    to_insert = plan.get("to_insert", [])
    if not to_insert:
        return 0

    inserted_count = 0
    async with factory() as session:
        for row in to_insert:
            user = User(
                id=row["id"],
                name=row["name"],
                email=User.normalize_email(row["email"]),
                password_hash=row["password_hash"],
                role="customer",
                is_active=True,
            )
            session.add(user)
            inserted_count += 1

        await session.commit()

        # Synchronize sequence so future auto-increment IDs start after max(id)
        bind = session.bind
        if bind and bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE(MAX(id), 1)) FROM users;")
            )
            await session.commit()

    return inserted_count


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite users to PostgreSQL.")
    parser.add_argument("--sqlite-path", default=str(BACKEND_DIR / "trustpay.db"), help="Path to SQLite database")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview migration without modifying data (default)")
    parser.add_argument("--apply", action="store_true", help="Apply migration to PostgreSQL")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path)
    print("=" * 60)
    print("TRUSTPAY AI – LEGACY USER MIGRATION TOOL")
    print("=" * 60)
    print(f"Source SQLite database: {sqlite_path}")

    plan = asyncio.run(plan_migration(sqlite_path))

    print(f"Status: {plan.get('status')}")
    print(f"Source SQLite user records: {plan.get('source_count')}")

    if plan.get("status") == "postgres_not_configured":
        print("\nNotice: PostgreSQL is not currently configured or reachable.")
        print("Source records are preserved. Set DATABASE_URL in backend/.env to connect.")
        for r in plan.get("records", []):
            print(f"  - Record ID {r['id']}: Name: {r['name']}, Email: {mask_email(r['email'])}")
        return

    print(f"Accounts ready to insert: {plan.get('to_insert_count')}")
    print(f"Accounts already matching: {plan.get('already_matching_count')}")
    print(f"ID conflicts: {plan.get('id_conflicts_count')}")
    print(f"Email conflicts: {plan.get('email_conflicts_count')}")

    if args.apply:
        if plan.get("to_insert_count", 0) > 0:
            print("\nApplying migration...")
            inserted = asyncio.run(apply_migration(plan))
            print(f"Successfully migrated {inserted} user account(s) to PostgreSQL.")
        else:
            print("\nNo new accounts to migrate.")
    else:
        print("\nDRY RUN ONLY. No data was modified.")
        print("To apply this migration, run with --apply after review.")


if __name__ == "__main__":
    main()

