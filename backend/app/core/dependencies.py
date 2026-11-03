import json
import base64
import hmac
import hashlib
from typing import Any, Callable
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db, get_session_factory
from app.models.user import User
from app.services.auth_service import AuthService


def get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Extract raw JWT bearer token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token is required.",
        )
    return authorization.removeprefix("Bearer ").strip()


def decode_legacy_token(token: str) -> int:
    """Decode legacy prototype HMAC token for transitional backwards compatibility."""
    try:
        header, payload, signature = token.split(".")
        message = f"{header}.{payload}".encode()
        expected = base64.urlsafe_b64encode(
            hmac.new(settings.TRUSTPAY_SECRET_KEY.encode(), message, hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(decoded["sub"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc


async def get_current_user(
    token: str = Depends(get_bearer_token),
) -> User:
    """
    FastAPI dependency resolving authenticated User from Bearer token.
    Validates PostgreSQL active session if database is configured;
    falls back gracefully to SQLite prototype lookup if PostgreSQL is not yet configured.
    """
    if settings.is_postgres_configured:
        factory = get_session_factory()
        if factory is not None:
            async with factory() as session:
                return await AuthService.get_current_user_from_token(session=session, token=token)

    # Transitional fallback for SQLite prototype
    try:
        user_id = decode_legacy_token(token)
    except HTTPException:
        # If legacy decode fails, try PyJWT decode for user_id
        from app.core.security import decode_access_token
        try:
            payload = decode_access_token(token)
            user_id = int(payload["sub"])
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token.",
            ) from exc

    try:
        from app.database import connect
        with connect() as conn:
            row = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account no longer exists.",
                )
            return User(
                id=row["id"],
                name=row["name"],
                email=row["email"],
                password_hash="",
                is_active=True,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication database is unavailable.",
        ) from exc


async def require_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """Ensure the authenticated user account is active."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or disabled.",
        )
    return user


def require_role(required_role: str) -> Callable[[User], User]:
    """Factory dependency enforcing a specific role requirement."""
    async def role_checker(user: User = Depends(require_active_user)) -> User:
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires '{required_role}' privileges.",
            )
        return user

    return role_checker


async def get_optional_current_user(
    authorization: str | None = Header(default=None),
) -> User | None:
    """
    Optional authentication dependency for catalog and platform inspection.
    Validates token if Authorization header is provided; allows guest access if omitted.
    """
    if not authorization:
        return None
    token = get_bearer_token(authorization)
    return await get_current_user(token=token)

