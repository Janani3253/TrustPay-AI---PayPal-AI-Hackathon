import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.core.ai_exceptions import (
    AIAuthenticationError,
    AINotConfiguredError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AIRateLimitError,
    AISchemaValidationError,
    AITimeoutError,
    EmptyShoppingRequestError,
    ShoppingRequestTooLongError,
)
from app.core.config import settings
from app.schemas.intent import StructuredIntentExtraction
from app.services.gemini_service import GeminiService


SAMPLE_VALID_JSON = """{
  "product_type": "laptop",
  "product_category": "laptops",
  "search_keywords": ["laptop", "16GB RAM", "512GB SSD"],
  "budget": {
    "amount": "60000.00",
    "currency": "INR",
    "comparison": "MAXIMUM",
    "scope": "UNSPECIFIED",
    "evidence": "under ₹60,000"
  },
  "mandatory_specifications": [
    {
      "name": "RAM",
      "operator": "GTE",
      "value": "16",
      "unit": "GB",
      "evidence": "16GB RAM"
    },
    {
      "name": "Storage",
      "operator": "GTE",
      "value": "512",
      "unit": "GB SSD",
      "evidence": "512GB SSD"
    }
  ],
  "preferences": [
    {
      "name": "Brand",
      "preference_type": "PREFERRED",
      "value": "ASUS",
      "evidence": "preferably ASUS"
    }
  ],
  "excluded_conditions": [
    {
      "condition": "refurbished",
      "evidence": "no refurbished"
    }
  ],
  "quantity": 1,
  "clarification_required": false,
  "clarification_questions": [],
  "unresolved_requirements": [],
  "extraction_warnings": []
}"""


@pytest.mark.asyncio
async def test_gemini_unconfigured_raises():
    """Verify AINotConfiguredError is raised when GEMINI_API_KEY is not set."""
    with patch.object(settings, "GEMINI_API_KEY", None):
        service = GeminiService()
        with pytest.raises(AINotConfiguredError):
            await service.extract_shopping_intent("Find a laptop")


@pytest.mark.asyncio
async def test_gemini_empty_request_raises():
    """Verify empty or whitespace-only shopping instruction raises EmptyShoppingRequestError."""
    with patch.object(settings, "GEMINI_API_KEY", "valid_key_12345678"):
        service = GeminiService()
        with pytest.raises(EmptyShoppingRequestError):
            await service.extract_shopping_intent("   ")


@pytest.mark.asyncio
async def test_gemini_request_too_long_raises():
    """Verify request exceeding character limit raises ShoppingRequestTooLongError."""
    with patch.object(settings, "GEMINI_API_KEY", "valid_key_12345678"):
        service = GeminiService()
        huge_text = "a" * (settings.INTENT_MAX_REQUEST_CHARS + 10)
        with pytest.raises(ShoppingRequestTooLongError):
            await service.extract_shopping_intent(huge_text)


@pytest.mark.asyncio
async def test_gemini_successful_async_extraction():
    """Verify valid model response is parsed into StructuredIntentExtraction."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = SAMPLE_VALID_JSON

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    service = GeminiService(client=mock_client)
    result = await service.extract_shopping_intent("I need a laptop under ₹60,000 with 16GB RAM, 512GB SSD, preferably ASUS, no refurbished")

    assert isinstance(result, StructuredIntentExtraction)
    assert result.product_type == "laptop"
    assert result.budget.amount == 60000.00
    assert result.budget.currency == "INR"
    assert len(result.mandatory_specifications) == 2
    assert result.mandatory_specifications[0].name == "RAM"
    assert result.preferences[0].value == "ASUS"
    assert result.excluded_conditions[0].condition == "refurbished"


@pytest.mark.asyncio
async def test_gemini_malformed_schema_raises():
    """Verify invalid model JSON schema raises AISchemaValidationError."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"product_type": 123, "quantity": "invalid_number"}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    service = GeminiService(client=mock_client)
    with pytest.raises(AISchemaValidationError):
        await service.extract_shopping_intent("Laptop with 16GB RAM")


@pytest.mark.asyncio
async def test_gemini_timeout_handling():
    """Verify timeout triggers AITimeoutError."""
    mock_client = MagicMock()

    async def slow_call(*args, **kwargs):
        await asyncio.sleep(0.5)

    mock_client.aio.models.generate_content = slow_call

    service = GeminiService(client=mock_client, timeout=0.05)
    with patch.object(settings, "GEMINI_MAX_RETRIES", 0):
        with pytest.raises(AITimeoutError):
            await service.extract_shopping_intent("Gaming laptop")


@pytest.mark.asyncio
async def test_gemini_rate_limit_and_quota_mapping():
    """Verify API error strings are correctly mapped to domain exceptions."""
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("Resource_exhausted quota exceeded for project"))

    service = GeminiService(client=mock_client)
    with patch.object(settings, "GEMINI_MAX_RETRIES", 0):
        with pytest.raises(AIQuotaExceededError):
            await service.extract_shopping_intent("Laptop")

    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API_KEY_INVALID: API key not valid"))
    with patch.object(settings, "GEMINI_MAX_RETRIES", 0):
        with pytest.raises(AIAuthenticationError):
            await service.extract_shopping_intent("Laptop")


@pytest.mark.asyncio
async def test_gemini_concurrency_semaphore():
    """Verify concurrent requests are bounded by semaphore."""
    mock_client = MagicMock()
    concurrent_count = 0
    max_observed = 0

    async def controlled_generate(*args, **kwargs):
        nonlocal concurrent_count, max_observed
        concurrent_count += 1
        if concurrent_count > max_observed:
            max_observed = concurrent_count
        await asyncio.sleep(0.02)
        concurrent_count -= 1
        resp = MagicMock()
        resp.text = SAMPLE_VALID_JSON
        return resp

    mock_client.aio.models.generate_content = controlled_generate
    service = GeminiService(client=mock_client)

    with patch.object(settings, "GEMINI_MAX_CONCURRENT_REQUESTS", 2):
        service._semaphore = asyncio.Semaphore(2)
        tasks = [service.extract_shopping_intent(f"Request {i}") for i in range(5)]
        await asyncio.gather(*tasks)
        assert max_observed <= 2

