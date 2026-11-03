from datetime import datetime, timezone
from typing import Optional
import sqlalchemy as sa
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.auth_session import AuthSession


class UserRepository:
    """Repository handling database operations for User and AuthSession models."""

    @staticmethod
    async def create_user(
        session: AsyncSession,
        name: str,
        email: str,
        password_hash: str,
        role: str = "customer",
        user_id: Optional[int] = None,
    ) -> User:
        """Create and persist a new user record."""
        normalized_email = User.normalize_email(email)
        user = User(
            name=name.strip(),
            email=normalized_email,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        if user_id is not None:
            user.id = user_id

        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """Retrieve user by integer primary key."""
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """Retrieve user by email address (case-insensitive)."""
        normalized_email = User.normalize_email(email)
        stmt = select(User).where(func.lower(User.email) == normalized_email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_password_hash(session: AsyncSession, user_id: int, new_hash: str) -> bool:
        """Update user password hash (e.g. after legacy migration upgrade)."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(password_hash=new_hash, updated_at=datetime.now(timezone.utc))
        )
        result = await session.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    async def create_session(
        session: AsyncSession,
        user_id: int,
        jti: str,
        expires_at: datetime,
    ) -> AuthSession:
        """Create and persist an authentication session."""
        auth_session = AuthSession(
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
        )
        session.add(auth_session)
        await session.flush()
        return auth_session

    @staticmethod
    async def get_active_session(session: AsyncSession, jti: str) -> Optional[AuthSession]:
        """Retrieve active session by JTI (not revoked and not expired)."""
        now = datetime.now(timezone.utc)
        stmt = select(AuthSession).where(
            AuthSession.jti == jti,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke_session(session: AsyncSession, jti: str) -> bool:
        """Revoke active session by setting revoked_at timestamp."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(AuthSession)
            .where(AuthSession.jti == jti, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        result = await session.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    async def sync_id_sequence(session: AsyncSession) -> None:
        """Synchronize the PostgreSQL auto-increment sequence with max ID."""
        bind = session.bind
        if bind and bind.dialect.name == "postgresql":
            await session.execute(
                sa.text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE(MAX(id), 1)) FROM users;")
            )

