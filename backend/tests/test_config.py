import pytest
from app.core.config import Settings


def test_default_config_loads():
    """Verify default configuration loads properly."""
    config = Settings(DATABASE_URL=None)
    assert config.APP_NAME == "TrustPay AI"
    assert config.APP_ENV == "development"
    assert config.DEBUG is True
    assert config.is_postgres_configured is False
    assert config.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_config_env_overrides():
    """Verify environment/explicit overrides work."""
    config = Settings(
        APP_NAME="TrustPay AI Test",
        APP_ENV="testing",
        DEBUG=False,
        TRUSTPAY_CORS_ORIGINS="http://test.local, https://app.example.com",
    )
    assert config.APP_NAME == "TrustPay AI Test"
    assert config.APP_ENV == "testing"
    assert config.DEBUG is False
    assert config.cors_origins == ["http://test.local", "https://app.example.com"]


def test_placeholder_database_urls_rejected():
    """Verify placeholder credentials in DATABASE_URL are not treated as configured."""
    placeholders = [
        None,
        "",
        "postgresql+psycopg://YOUR_USERNAME:YOUR_PASSWORD@localhost:5432/trustpay_ai",
        "postgresql://username:password@localhost:5432/db",
        "postgresql+psycopg://replace-with:pass@localhost:5432/db",
        "sqlite:///./test.db",  # Not a postgresql URL
    ]
    for url in placeholders:
        config = Settings(DATABASE_URL=url)
        assert config.is_postgres_configured is False, f"URL {url} should not be considered configured"


def test_valid_database_url_accepted():
    """Verify valid PostgreSQL URL without placeholders is considered configured."""
    valid_url = "postgresql+psycopg://trustpay_admin:secure_pass_123@localhost:5432/trustpay_production"
    config = Settings(DATABASE_URL=valid_url)
    assert config.is_postgres_configured is True
    assert config.get_safe_database_url() == "postgresql+psycopg://trustpay_admin:***@localhost:5432/trustpay_production"


def test_safe_database_url_masks_password():
    """Verify password masking in get_safe_database_url."""
    url = "postgresql+psycopg://dbuser:supersecret987@dbhost:5432/dbname"
    config = Settings(DATABASE_URL=url)
    safe_url = config.get_safe_database_url()
    assert "supersecret987" not in safe_url
    assert safe_url == "postgresql+psycopg://dbuser:***@dbhost:5432/dbname"


def test_repr_does_not_expose_database_password():
    """Verify __repr__ does not expose sensitive database URL."""
    url = "postgresql+psycopg://dbuser:supersecret987@dbhost:5432/dbname"
    config = Settings(DATABASE_URL=url)
    repr_str = repr(config)
    assert "supersecret987" not in repr_str
    assert "DATABASE_CONFIGURED=True" in repr_str

