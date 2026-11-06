from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.base import Base
from app.models.user import User
from app.models.auth_session import AuthSession
from app.repositories.user_repository import UserRepository


@pytest.fixture
async def db_session():
    """Create an isolated in-memory SQLite database session for unit tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


def test_user_model_attributes_and_dict_access():
    """Verify User model attributes, email normalization, and dictionary-like access."""
    user = User(
        id=7,
        name="Alex Morgan",
        email="Alex.Morgan@Example.com",
        password_hash="$2b$12$somehashvalue",
    )
    assert user.id == 7
    assert user.name == "Alex Morgan"
    assert User.normalize_email(user.email) == "alex.morgan@example.com"
    # Backwards compatibility check
    assert user["id"] == 7
    assert user["name"] == "Alex Morgan"
    assert user["email"] == "Alex.Morgan@Example.com"
    assert "id" in user
    assert "nonexistent" not in user
    with pytest.raises(KeyError):
        _ = user["nonexistent"]


def test_auth_session_active_and_revocation():
    """Verify AuthSession is_active property and revoke method."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=2)
    session = AuthSession(
        user_id=1,
        jti="test-jti-uuid",
        expires_at=future,
    )
    assert session.is_active is True

    session.revoke()
    assert session.is_active is False
    assert session.revoked_at is not None


@pytest.mark.asyncio
async def test_user_repository_crud(db_session: AsyncSession):
    """Verify UserRepository methods with database persistence."""
    # Create user
    user = await UserRepository.create_user(
        session=db_session,
        name="Taylor Swift",
        email="TAYLOR@example.com",
        password_hash="$2b$12$hash123",
        role="customer",
        user_id=101,  # Explicit ID preservation
    )
    await db_session.commit()

    assert user.id == 101
    assert user.email == "taylor@example.com"

    # Get by ID
    found_by_id = await UserRepository.get_by_id(db_session, 101)
    assert found_by_id is not None
    assert found_by_id.name == "Taylor Swift"

    # Get by Email (case-insensitive)
    found_by_email = await UserRepository.get_by_email(db_session, "Taylor@Example.COM")
    assert found_by_email is not None
    assert found_by_email.id == 101

    # Update password hash
    updated = await UserRepository.update_password_hash(db_session, 101, "$2b$12$newhash456")
    await db_session.commit()
    assert updated is True

    reloaded = await UserRepository.get_by_id(db_session, 101)
    assert reloaded.password_hash == "$2b$12$newhash456"


@pytest.mark.asyncio
async def test_user_repository_session_lifecycle(db_session: AsyncSession):
    """Verify session creation, lookup, and server-side revocation."""
    user = await UserRepository.create_user(
        session=db_session,
        name="Session Test User",
        email="session_user@example.com",
        password_hash="$2b$12$hash",
    )
    await db_session.commit()

    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    auth_session = await UserRepository.create_session(
        session=db_session,
        user_id=user.id,
        jti="active-jti-12345",
        expires_at=expires,
    )
    await db_session.commit()

    # Verify session is active
    found_session = await UserRepository.get_active_session(db_session, "active-jti-12345")
    assert found_session is not None
    assert found_session.user_id == user.id

    # Revoke session
    revoked = await UserRepository.revoke_session(db_session, "active-jti-12345")
    await db_session.commit()
    assert revoked is True

    # Active lookup returns None after revocation
    inactive_session = await UserRepository.get_active_session(db_session, "active-jti-12345")
    assert inactive_session is None

