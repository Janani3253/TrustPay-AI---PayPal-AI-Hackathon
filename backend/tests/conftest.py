import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Use an isolated temp database path for tests to avoid touching trustpay.db
TEMP_TEST_DB = Path(tempfile.gettempdir()) / "trustpay_test_isolated.db"
os.environ["TRUSTPAY_DATABASE_PATH"] = str(TEMP_TEST_DB)

from app.database import initialize_database
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def clean_test_temp_db() -> Generator[None, None, None]:
    """Ensure isolated test database file is initialized and cleaned up after testing."""
    initialize_database()
    yield
    if TEMP_TEST_DB.exists():
        try:
            TEMP_TEST_DB.unlink()
        except Exception:
            pass


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Async client fixture for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
