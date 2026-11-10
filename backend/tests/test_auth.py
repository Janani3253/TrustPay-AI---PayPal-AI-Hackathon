import base64
import hashlib
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.db.base import Base
from app.main import app
from app.models.user import User


@pytest_asyncio.fixture
async def test_app_client():
    """Create a test client backed by an isolated in-memory SQLite database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        execution_options={"schema_translate_map": {"trustpay_ai": None}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Also mock session factory so dependencies calling get_session_factory() use the test engine
    from unittest.mock import patch
    from app.core.config import settings

    with patch("app.core.dependencies.get_session_factory", return_value=session_maker):
        with patch.object(settings, "DATABASE_URL", "postgresql+psycopg://test_user:test_pass@localhost:5432/trustpay_ai"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, session_maker

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_register_success_and_contract(test_app_client):
    """Verify registration endpoint adheres exactly to frontend AuthResponse contract."""
    client, _ = test_app_client
    payload = {
        "name": "Alex Carter",
        "email": "alex.carter@example.com",
        "password": "SecurePassword2026!",
    }
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()

    # Exact frontend contract checks
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["name"] == "Alex Carter"
    assert data["user"]["email"] == "alex.carter@example.com"
    assert isinstance(data["user"]["id"], int)
    # Password hash must NEVER be leaked
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email_409(test_app_client):
    """Verify duplicate email registration returns 409 Conflict."""
    client, _ = test_app_client
    payload = {
        "name": "First User",
        "email": "duplicate@example.com",
        "password": "SecurePassword1!",
    }
    res1 = await client.post("/api/auth/register", json=payload)
    assert res1.status_code == 201

    # Second attempt with case variation
    payload2 = {
        "name": "Second User",
        "email": "DUPLICATE@example.com",
        "password": "SecurePassword2!",
    }
    res2 = await client.post("/api/auth/register", json=payload2)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password_422(test_app_client):
    """Verify passwords shorter than 8 characters are rejected."""
    client, _ = test_app_client
    payload = {
        "name": "Test User",
        "email": "test@example.com",
        "password": "short",
    }
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success_and_invalid_credentials(test_app_client):
    """Verify login with correct credentials succeeds and bad credentials fail with 401."""
    client, _ = test_app_client
    # Register first
    await client.post("/api/auth/register", json={
        "name": "Login User",
        "email": "login_user@example.com",
        "password": "CorrectPassword123!",
    })

    # Successful login
    login_res = await client.post("/api/auth/login", json={
        "email": "login_user@example.com",
        "password": "CorrectPassword123!",
    })
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "login_user@example.com"

    # Wrong password
    bad_pw_res = await client.post("/api/auth/login", json={
        "email": "login_user@example.com",
        "password": "WrongPassword123!",
    })
    assert bad_pw_res.status_code == 401
    assert "incorrect" in bad_pw_res.json()["detail"].lower()

    # Nonexistent email
    bad_email_res = await client.post("/api/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "CorrectPassword123!",
    })
    assert bad_email_res.status_code == 401


@pytest.mark.asyncio
async def test_login_legacy_pbkdf2_auto_upgrade(test_app_client):
    """Verify legacy PBKDF2 hash authenticates and is upgraded to bcrypt in place."""
    client, session_maker = test_app_client

    # Directly insert legacy user with PBKDF2 hash
    password = "LegacyPasswordToUpgrade123!"
    salt = b"test_salt_legacy"
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    legacy_hash = f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(derived).decode()}"

    async with session_maker() as session:
        user = User(
            name="Legacy Customer",
            email="legacy@example.com",
            password_hash=legacy_hash,
            role="customer",
        )
        session.add(user)
        await session.commit()

    # Authenticate with legacy password
    login_res = await client.post("/api/auth/login", json={
        "email": "legacy@example.com",
        "password": password,
    })
    assert login_res.status_code == 200

    # Verify password hash was upgraded to bcrypt in database
    async with session_maker() as session:
        from app.repositories.user_repository import UserRepository
        updated_user = await UserRepository.get_by_email(session, "legacy@example.com")
        assert updated_user is not None
        assert updated_user.password_hash.startswith("$2")


@pytest.mark.asyncio
async def test_get_me_and_logout_revocation(test_app_client):
    """Verify /api/auth/me returns current user and /api/auth/logout revokes session."""
    client, _ = test_app_client
    reg_res = await client.post("/api/auth/register", json={
        "name": "Session Customer",
        "email": "session.cust@example.com",
        "password": "CustomerPassword123!",
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # /api/auth/me works
    me_res = await client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "session.cust@example.com"

    # /api/users/profile works
    profile_res = await client.get("/api/users/profile", headers=headers)
    assert profile_res.status_code == 200
    assert profile_res.json()["role"] == "customer"

    # Logout revokes session on server
    logout_res = await client.post("/api/auth/logout", headers=headers)
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Logged out successfully"

    # Subsequent request using the revoked token must fail with 401
    me_after_logout = await client.get("/api/auth/me", headers=headers)
    assert me_after_logout.status_code == 401
    assert "revoked" in me_after_logout.json()["detail"].lower()
