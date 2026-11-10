import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from sqlalchemy import MetaData
from app.db.base import Base
from app.core.database import (
    normalize_database_url,
    get_async_engine,
    get_db,
    check_db_connectivity,
    close_db_engine,
)
from app.core.config import settings


def test_base_declarative_metadata():
    """Verify Base has SQLAlchemy MetaData."""
    assert isinstance(Base.metadata, MetaData)


def test_normalize_database_url():
    """Verify URL scheme normalization for async psycopg including Render URLs."""
    assert normalize_database_url(None) is None
    assert normalize_database_url("") is None
    assert (
        normalize_database_url("postgresql://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    # Render postgres:// prefix normalization
    assert (
        normalize_database_url("postgres://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    # Render host with automatic SSL requirement injection
    assert (
        normalize_database_url("postgres://user:pass@dpg-xxx-a.oregon-postgres.render.com/trustpay")
        == "postgresql+psycopg://user:pass@dpg-xxx-a.oregon-postgres.render.com/trustpay?sslmode=require"
    )


@pytest.mark.asyncio
async def test_get_db_unconfigured_raises():
    """Verify get_db raises HTTPException 503 when database is unconfigured."""
    with patch.object(settings, "DATABASE_URL", None):
        generator = get_db()
        with pytest.raises(HTTPException) as exc_info:
            await generator.__anext__()
        assert exc_info.value.status_code == 503
        assert "PostgreSQL database is not configured" in exc_info.value.detail


@pytest.mark.asyncio
async def test_check_db_connectivity_not_configured():
    """Verify check_db_connectivity returns not_configured when DATABASE_URL is missing."""
    with patch.object(settings, "DATABASE_URL", None):
        result = await check_db_connectivity()
        assert result["status"] == "not_configured"
        assert result["engine"] == "PostgreSQL"
        assert "message" in result


@pytest.mark.asyncio
async def test_check_db_connectivity_connected():
    """Verify check_db_connectivity returns connected when PostgreSQL SELECT 1 succeeds."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = "PostgreSQL 16.4 on x86_64-pc-windows-msvc"

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_conn

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_cm

    with patch.object(settings, "DATABASE_URL", "postgresql+psycopg://app_user:valid_secret@localhost:5432/trustpay"):
        with patch("app.core.database.get_async_engine", return_value=mock_engine):
            result = await check_db_connectivity()
            assert result["status"] == "connected"
            assert result["engine"] == "PostgreSQL"
            assert result["version"] == "16"


@pytest.mark.asyncio
async def test_check_db_connectivity_unavailable():
    """Verify check_db_connectivity returns unavailable on connection error without leaking credentials."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = ConnectionRefusedError("Connection refused to port 5432")

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_cm

    with patch.object(settings, "DATABASE_URL", "postgresql+psycopg://app_user:valid_secret@localhost:5432/trustpay"):
        with patch("app.core.database.get_async_engine", return_value=mock_engine):
            result = await check_db_connectivity()
            assert result["status"] == "unavailable"
            assert result["engine"] == "PostgreSQL"
            assert "error_type" in result
            # Ensure no credentials or raw stack trace leaked
            assert "Could not connect to PostgreSQL database." in result["message"]
