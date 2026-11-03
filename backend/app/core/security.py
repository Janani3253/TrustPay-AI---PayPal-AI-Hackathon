import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple
import bcrypt
import jwt
from app.core.config import settings


class PasswordValidationError(ValueError):
    """Raised when a password fails policy checks."""
    pass


class TokenSecurityError(ValueError):
    """Raised when a JWT token is invalid, expired, or malformed."""
    pass


def validate_password_strength(password: str) -> None:
    """Validate password length and character constraints."""
    if not password:
        raise PasswordValidationError("Password cannot be empty.")
    if len(password) < 8:
        raise PasswordValidationError("Password must be at least 8 characters long.")
    # Bcrypt truncates passwords after 72 bytes
    if len(password.encode("utf-8")) > 72:
        raise PasswordValidationError("Password must not exceed 72 bytes.")


def hash_password(password: str) -> str:
    """Hash password using bcrypt with configured salt rounds."""
    validate_password_strength(password)
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def is_legacy_pbkdf2_hash(stored_hash: str) -> bool:
    """Determine whether stored hash is in the prototype's PBKDF2 salt:hash format."""
    if not stored_hash or not isinstance(stored_hash, str):
        return False
    # Bcrypt hashes start with $2a$, $2b$, or $2y$
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    parts = stored_hash.split(":")
    return len(parts) == 2


def verify_legacy_pbkdf2_password(plain_password: str, stored_hash: str) -> bool:
    """Verify password against legacy PBKDF2-HMAC hash used in prototype."""
    try:
        salt_text, expected_text = stored_hash.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
        actual = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Verify password against either modern bcrypt or legacy PBKDF2 format."""
    if not plain_password or not stored_hash:
        return False

    if is_legacy_pbkdf2_hash(stored_hash):
        return verify_legacy_pbkdf2_password(plain_password, stored_hash)

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Check if hash should be upgraded to modern bcrypt."""
    return is_legacy_pbkdf2_hash(stored_hash)


def create_access_token(
    user_id: int,
    custom_claims: Dict[str, Any] | None = None,
) -> Tuple[str, str, datetime]:
    """
    Create a signed JWT access token.
    Returns:
        (token_string, jti, expires_at)
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    if custom_claims:
        # Prevent overriding critical claims
        for k, v in custom_claims.items():
            if k not in payload:
                payload[k] = v

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return token, jti, expires_at


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT access token using PyJWT.
    Enforces signature, expiration, issuer, audience, and required claims.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": ["sub", "jti", "exp", "iss", "aud"],
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenSecurityError("Token has expired.") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenSecurityError("Invalid token issuer.") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenSecurityError("Invalid token audience.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenSecurityError("Invalid authentication token.") from exc

