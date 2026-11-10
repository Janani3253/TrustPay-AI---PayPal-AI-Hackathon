import os
import sqlite3
import tempfile
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.user import User
from scripts.migrate_legacy_users import (
    apply_migration,
    mask_email,
    plan_migration,
    read_sqlite_users,
)


@pytest.fixture
def temp_sqlite_db():
    """Create a temporary SQLite database with mock legacy users."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    # Insert two test users
    conn.execute(
        "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (1, "Legacy Alice", "alice@example.com", "legacy_pbkdf2_hash_alice:salt1", "2026-10-01T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (5, "Legacy Bob", "bob@example.com", "legacy_pbkdf2_hash_bob:salt2", "2026-10-02T14:30:00Z"),
    )
    conn.commit()
    conn.close()

    yield db_path

    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


def test_mask_email():
    """Verify email masking protects privacy."""
    assert mask_email("alex@example.com") == "a***x@example.com"
    assert mask_email("j@test.com") == "j***@test.com"
    assert mask_email("me@domain.org") == "m***@domain.org"
    assert mask_email("invalid-email") == "***"


def test_read_sqlite_users(temp_sqlite_db: Path):
    """Verify SQLite users are extracted in read-only mode."""
    records = read_sqlite_users(temp_sqlite_db)
    assert len(records) == 2
    assert records[0]["id"] == 1
    assert records[0]["name"] == "Legacy Alice"
    assert records[1]["id"] == 5
    assert records[1]["name"] == "Legacy Bob"


@pytest.mark.asyncio
async def test_migration_plan_and_apply(temp_sqlite_db: Path):
    """Verify migration planning and application preserves integer primary-key IDs."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        execution_options={"schema_translate_map": {"trustpay_ai": None}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    from unittest.mock import patch
    from app.core.config import settings
    with patch("scripts.migrate_legacy_users.get_async_engine", return_value=engine):
        with patch("scripts.migrate_legacy_users.get_session_factory", return_value=session_maker):
            with patch.object(settings, "DATABASE_URL", "postgresql+psycopg://test_user:test_pass@localhost:5432/trustpay_ai"):
                # 1. Plan migration
                plan = await plan_migration(temp_sqlite_db)
                assert plan["status"] == "ready"
                assert plan["source_count"] == 2
                assert plan["to_insert_count"] == 2
                assert plan["already_matching_count"] == 0

                # 2. Apply migration
                inserted = await apply_migration(plan)
                assert inserted == 2

                # 3. Verify destination records
                async with session_maker() as session:
                    from sqlalchemy import select
                    stmt = select(User).order_by(User.id)
                    result = await session.execute(stmt)
                    users = result.scalars().all()
                    assert len(users) == 2
                    assert users[0].id == 1
                    assert users[0].email == "alice@example.com"
                    assert users[1].id == 5
                    assert users[1].email == "bob@example.com"

                # 4. Running plan again shows already matching (idempotence)
                plan2 = await plan_migration(temp_sqlite_db)
                assert plan2["to_insert_count"] == 0
                assert plan2["already_matching_count"] == 2

    await engine.dispose()
