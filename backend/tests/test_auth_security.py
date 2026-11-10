import base64
import hashlib
import time
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    is_legacy_pbkdf2_hash,
    needs_rehash,
    validate_password_strength,
    verify_password,
    PasswordValidationError,
    TokenSecurityError,
)


def test_password_validation():
    """Verify password length and boundary rules."""
    validate_password_strength("validPassword123")

    with pytest.raises(PasswordValidationError, match="cannot be empty"):
        validate_password_strength("")

    with pytest.raises(PasswordValidationError, match="at least 8 characters"):
        validate_password_strength("short")

    with pytest.raises(PasswordValidationError, match="not exceed 72 bytes"):
        validate_password_strength("a" * 73)


def test_bcrypt_hashing_and_verification():
    """Verify bcrypt hash generation and constant-time verification."""
    password = "CustomerSecurePassword2026!"
    hashed = hash_password(password)

    assert hashed.startswith("$2")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert needs_rehash(hashed) is False


def test_legacy_pbkdf2_hash_verification():
    """Verify legacy PBKDF2-HMAC hash format compatibility."""
    password = "LegacyPassword123"
    salt = b"test_salt_16_byte"
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    legacy_hash = f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(derived).decode()}"

    assert is_legacy_pbkdf2_hash(legacy_hash) is True
    assert needs_rehash(legacy_hash) is True
    assert verify_password(password, legacy_hash) is True
    assert verify_password("IncorrectPassword", legacy_hash) is False


def test_jwt_create_and_decode():
    """Verify JWT access token creation and decoding."""
    user_id = 42
    token, jti, expires_at = create_access_token(user_id)

    assert isinstance(token, str)
    assert len(jti) == 36  # UUID length
    assert expires_at > datetime.now(timezone.utc)

    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["jti"] == jti
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE


def test_jwt_expired_token():
    """Verify expired JWT is rejected."""
    now = datetime.now(timezone.utc) - timedelta(hours=2)
    expired_payload = {
        "sub": "99",
        "jti": "expired-jti-uuid",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    expired_token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenSecurityError, match="expired"):
        decode_access_token(expired_token)


def test_jwt_invalid_signature():
    """Verify token signed with an untrusted secret is rejected."""
    user_id = 10
    token, _, _ = create_access_token(user_id)
    tampered_token = jwt.encode(
        {"sub": "10", "jti": "fake", "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()), "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        "wrong-untrusted-secret-key-32-chars!!",
        algorithm="HS256",
    )

    with pytest.raises(TokenSecurityError, match="Invalid authentication token"):
        decode_access_token(tampered_token)


def test_jwt_invalid_issuer_or_audience():
    """Verify tokens with mismatched issuer or audience are rejected."""
    now = datetime.now(timezone.utc)
    bad_iss_payload = {
        "sub": "10",
        "jti": "jti-1",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "unauthorized-issuer",
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(bad_iss_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenSecurityError, match="Invalid token issuer"):
        decode_access_token(token)

