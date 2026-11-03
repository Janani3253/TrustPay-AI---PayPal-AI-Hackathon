import logging
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
    PasswordValidationError,
    TokenSecurityError,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
    UserProfileResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)


def mirror_user_to_sqlite(user_id: int, name: str, email: str, password_hash: str) -> None:
    """Transitional bridge: mirror newly created user to SQLite to support legacy cart/order FKs."""
    try:
        from app.database import connect
        with connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO users (id, name, email, password_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, name.strip(), email.lower().strip(), password_hash, datetime.now(timezone.utc).isoformat()),
            )
    except Exception as exc:
        logger.warning("Could not mirror user %s to legacy SQLite: %s", user_id, exc)


class AuthService:
    """Service encapsulating user registration, authentication, and session handling."""

    @staticmethod
    async def register(session: AsyncSession, payload: RegisterRequest) -> AuthResponse:
        """Register a new customer account."""
        try:
            validate_password_strength(payload.password)
        except PasswordValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        normalized_email = User.normalize_email(payload.email)

        # Check existing user
        existing_user = await UserRepository.get_by_email(session, normalized_email)
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        hashed_pw = hash_password(payload.password)

        try:
            user = await UserRepository.create_user(
                session=session,
                name=payload.name,
                email=normalized_email,
                password_hash=hashed_pw,
                role="customer",
            )
            await session.commit()
            await session.refresh(user)
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            ) from exc

        # Mirror user to SQLite for transitional legacy compatibility
        mirror_user_to_sqlite(user.id, user.name, user.email, hashed_pw)

        # Create session and issue token
        token, jti, expires_at = create_access_token(user.id)
        await UserRepository.create_session(session, user.id, jti, expires_at)
        await session.commit()

        user_resp = UserResponse(id=user.id, name=user.name, email=user.email)
        return AuthResponse(access_token=token, token_type="bearer", user=user_resp)

    @staticmethod
    async def login(session: AsyncSession, payload: LoginRequest) -> AuthResponse:
        """Authenticate user credentials and issue a new session token."""
        normalized_email = User.normalize_email(payload.email)
        user = await UserRepository.get_by_email(session, normalized_email)

        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email or password is incorrect.",
            )

        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email or password is incorrect.",
            )

        # Upgrade legacy PBKDF2 hash to bcrypt on successful login
        if needs_rehash(user.password_hash):
            new_hash = hash_password(payload.password)
            await UserRepository.update_password_hash(session, user.id, new_hash)
            user.password_hash = new_hash
            await session.commit()
            mirror_user_to_sqlite(user.id, user.name, user.email, new_hash)

        # Create session and issue token
        token, jti, expires_at = create_access_token(user.id)
        await UserRepository.create_session(session, user.id, jti, expires_at)
        await session.commit()

        user_resp = UserResponse(id=user.id, name=user.name, email=user.email)
        return AuthResponse(access_token=token, token_type="bearer", user=user_resp)

    @staticmethod
    async def get_current_user_from_token(session: AsyncSession, token: str) -> User:
        """Validate token and active session, returning authenticated user."""
        try:
            payload = decode_access_token(token)
        except TokenSecurityError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

        user_id_str = payload.get("sub")
        jti = payload.get("jti")
        if not user_id_str or not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload.",
            )

        try:
            user_id = int(user_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user subject in token.",
            )

        # Validate that session is still active and not revoked
        auth_session = await UserRepository.get_active_session(session, jti)
        if auth_session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has been revoked or has expired.",
            )

        user = await UserRepository.get_by_id(session, user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account no longer exists or is inactive.",
            )

        return user

    @staticmethod
    async def logout(session: AsyncSession, token: str) -> LogoutResponse:
        """Revoke active authentication session."""
        try:
            payload = decode_access_token(token)
            jti = payload.get("jti")
            if jti:
                await UserRepository.revoke_session(session, jti)
                await session.commit()
        except Exception:
            # Safe idempotent logout even if token parsing fails
            pass
        return LogoutResponse(message="Logged out successfully")

