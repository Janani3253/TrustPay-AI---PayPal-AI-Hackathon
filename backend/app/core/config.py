from pathlib import Path
from typing import Any, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = BACKEND_DIR / ".env"

PLACEHOLDER_MARKERS = {
    "your_username",
    "your_password",
    "username:password",
    "replace-with",
    "placeholder",
}


class Settings(BaseSettings):
    """Centralized application settings for TrustPay AI."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Application Settings
    APP_NAME: str = "TrustPay AI"
    APP_ENV: str = "development"
    DEBUG: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on", "t", "dev", "development")
        return bool(v)

    # PostgreSQL Database Settings
    DATABASE_URL: str | None = Field(default=None)
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Authentication & Security Settings (Phase 2)
    JWT_SECRET_KEY: str = Field(
        default="dev-jwt-secret-key-at-least-32-chars-trustpay-ai-intentlock"
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "trustpay-ai"
    JWT_AUDIENCE: str = "trustpay-ai-frontend"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours default matching prototype
    BCRYPT_ROUNDS: int = 12

    # Existing Legacy / External Settings (Preserved for compatibility)
    TRUSTPAY_SECRET_KEY: str = "local-development-key-change-before-deployment"
    TRUSTPAY_DATABASE_PATH: str = str(BACKEND_DIR / "trustpay.db")
    TRUSTPAY_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_ENVIRONMENT: str = "sandbox"
    PAYPAL_API_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Product Provider Settings (Phase 3)
    DUMMYJSON_BASE_URL: str = "https://dummyjson.com"
    DUMMYJSON_ENABLED: bool = True
    PRODUCT_REQUEST_TIMEOUT_SECONDS: float = 10.0
    PRODUCT_CACHE_TTL_SECONDS: int = 300
    PRODUCT_CATEGORY_CACHE_TTL_SECONDS: int = 1800
    PRODUCT_CACHE_MAX_ENTRIES: int = 500
    PRODUCT_MAX_PAGE_SIZE: int = 200
    PRODUCT_RETRY_ATTEMPTS: int = 2

    # Gemini AI & Intent Extraction Settings (Phase 4)
    GEMINI_API_KEY: str | None = Field(default=None)
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: float = 30.0
    GEMINI_MAX_RETRIES: int = 1
    GEMINI_MAX_CONCURRENT_REQUESTS: int = 5
    INTENT_MAX_REQUEST_CHARS: int = 4000
    INTENT_MAX_OUTPUT_TOKENS: int = 2000

    # Prompt Injection & Content Security Settings (Phase 5)
    SECURITY_SCAN_MAX_CONTENT_CHARS: int = 20000
    SECURITY_SCAN_MAX_FIELDS: int = 20
    SECURITY_SCAN_MAX_FINDINGS: int = 50
    SECURITY_SCAN_MAX_GEMINI_OUTPUT_TOKENS: int = 1500
    SECURITY_SCAN_MAX_CONCURRENT_AI_REQUESTS: int = 3
    SECURITY_SCAN_CACHE_TTL_SECONDS: int = 300
    SECURITY_SCAN_CACHE_MAX_ENTRIES: int = 500

    @property
    def cors_origins(self) -> List[str]:
        """Return parsed list of allowed CORS origins."""
        return [
            origin.strip()
            for origin in self.TRUSTPAY_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def is_postgres_configured(self) -> bool:
        """Check if a valid, non-placeholder PostgreSQL URL is configured."""
        if not self.DATABASE_URL:
            return False
        url_lower = self.DATABASE_URL.lower().strip()
        if not url_lower.startswith(("postgresql://", "postgresql+psycopg://")):
            return False
        for marker in PLACEHOLDER_MARKERS:
            if marker in url_lower:
                return False
        return True

    @property
    def is_paypal_configured(self) -> bool:
        """Check if PayPal Sandbox credentials are valid and non-placeholder."""
        if not self.PAYPAL_CLIENT_ID or not self.PAYPAL_CLIENT_SECRET:
            return False
        client_id_lower = self.PAYPAL_CLIENT_ID.lower()
        return not any(marker in client_id_lower for marker in PLACEHOLDER_MARKERS)

    @property
    def is_gemini_configured(self) -> bool:
        """Check if a valid, non-placeholder Gemini API key is configured."""
        if not self.GEMINI_API_KEY:
            return False
        key = self.GEMINI_API_KEY.strip()
        if not key or len(key) < 10:
            return False
        for marker in PLACEHOLDER_MARKERS:
            if marker in key.lower():
                return False
        return True

    def get_safe_database_url(self) -> str | None:
        """Return the database URL with masked password for safe logging/display."""
        if not self.DATABASE_URL:
            return None
        try:
            # Mask credentials if present
            if "@" in self.DATABASE_URL and "://" in self.DATABASE_URL:
                scheme_part, rest = self.DATABASE_URL.split("://", 1)
                user_pass, host_db = rest.split("@", 1)
                if ":" in user_pass:
                    user, _ = user_pass.split(":", 1)
                    return f"{scheme_part}://{user}:***@{host_db}"
                return f"{scheme_part}://***@{host_db}"
            return self.DATABASE_URL
        except Exception:
            return "***"

    def __repr__(self) -> str:
        return (
            f"Settings(APP_NAME={self.APP_NAME!r}, APP_ENV={self.APP_ENV!r}, "
            f"DEBUG={self.DEBUG!r}, DATABASE_CONFIGURED={self.is_postgres_configured!r})"
        )


settings = Settings()
