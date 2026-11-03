from typing import Any, AsyncGenerator, Dict
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import settings

# Global async engine and session factory holders
_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def normalize_database_url(url: str | None) -> str | None:
    """Ensure the URL uses the async psycopg driver."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_async_engine() -> AsyncEngine | None:
    """Retrieve or create the SQLAlchemy async engine if configured."""
    global _async_engine, _async_session_factory

    if not settings.is_postgres_configured:
        return None

    if _async_engine is None:
        db_url = normalize_database_url(settings.DATABASE_URL)
        _async_engine = create_async_engine(
            db_url,
            echo=settings.DB_ECHO,
            pool_pre_ping=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
        _async_session_factory = async_sessionmaker(
            bind=_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Retrieve the session factory, initializing engine if needed."""
    global _async_session_factory
    if _async_session_factory is None:
        get_async_engine()
    return _async_session_factory


async def close_db_engine() -> None:
    """Dispose of the asynchronous engine connection pool cleanly."""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL database is not configured. Set a valid DATABASE_URL in .env",
        )

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connectivity() -> Dict[str, Any]:
    """Check PostgreSQL connectivity using SELECT 1 without exposing secrets."""
    if not settings.is_postgres_configured:
        return {
            "status": "not_configured",
            "engine": "PostgreSQL",
            "message": "DATABASE_URL is not set or contains placeholder credentials.",
        }

    engine = get_async_engine()
    if engine is None:
        return {
            "status": "not_configured",
            "engine": "PostgreSQL",
            "message": "Engine initialization skipped due to missing configuration.",
        }

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version();"))
            version_row = result.scalar()
            version_str = "16"
            if version_row and "PostgreSQL" in str(version_row):
                # Extract major version number if available
                parts = str(version_row).split()
                if len(parts) >= 2:
                    version_str = parts[1].split(".")[0]

            return {
                "status": "connected",
                "engine": "PostgreSQL",
                "version": version_str,
            }
    except Exception as exc:
        # Sanitize error to avoid leaking credentials
        error_type = type(exc).__name__
        return {
            "status": "unavailable",
            "engine": "PostgreSQL",
            "error_type": error_type,
            "message": "Could not connect to PostgreSQL database.",
        }

