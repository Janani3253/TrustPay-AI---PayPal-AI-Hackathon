import asyncio
from logging.config import fileConfig
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure backend directory is in sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings
from app.core.database import normalize_database_url
from app.db.base import Base
import app.models  # Register all models with Base.metadata

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for 'autogenerate' support
target_metadata = Base.metadata


def get_url() -> str:
    """Retrieve normalized PostgreSQL connection URL from settings."""
    if settings.is_postgres_configured:
        return normalize_database_url(settings.DATABASE_URL) or ""
    # Fallback placeholder to allow offline generation
    return "postgresql+psycopg://user:pass@localhost:5432/trustpay_ai"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table_schema="trustpay_ai",
        version_table="alembic_version",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    import sqlalchemy as sa

    # Ensure trustpay_ai schema exists before Alembic checks or creates version table
    connection.execute(sa.text("CREATE SCHEMA IF NOT EXISTS trustpay_ai"))
    # Set search_path so unqualified migration operations resolve strictly inside trustpay_ai
    connection.execute(sa.text("SET search_path TO trustpay_ai"))

    def include_object(object, name, type_, reflected, compare_to):
        if type_ == "table":
            # Only track and inspect tables that belong to the trustpay_ai schema
            return getattr(object, "schema", None) == "trustpay_ai"
        return True

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="trustpay_ai",
        version_table="alembic_version",
        include_schemas=False,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using AsyncEngine."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

