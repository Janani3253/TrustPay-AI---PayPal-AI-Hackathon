from typing import Optional


class AIException(Exception):
    """Base exception for all AI/Gemini integration errors."""

    def __init__(self, message: str, code: str = "AI_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AINotConfiguredError(AIException):
    def __init__(self, message: str = "Google Gemini AI is not configured. Please configure GEMINI_API_KEY in backend/.env."):
        super().__init__(message=message, code="AI_NOT_CONFIGURED", status_code=503)


class AIAuthenticationError(AIException):
    def __init__(self, message: str = "Gemini authentication failed. Please verify the configured GEMINI_API_KEY."):
        super().__init__(message=message, code="AI_AUTHENTICATION_FAILED", status_code=503)


class AIQuotaExceededError(AIException):
    def __init__(self, message: str = "Gemini API quota has been exhausted. Please verify your billing/quota tier."):
        super().__init__(message=message, code="AI_QUOTA_EXCEEDED", status_code=503)


class AIRateLimitError(AIException):
    def __init__(self, message: str = "Gemini API rate limit reached after retries. Please retry in a few moments."):
        super().__init__(message=message, code="AI_RATE_LIMITED", status_code=503)


class AITimeoutError(AIException):
    def __init__(self, message: str = "Gemini request timed out while generating intent extraction."):
        super().__init__(message=message, code="AI_TIMEOUT", status_code=504)


class AIProviderUnavailableError(AIException):
    def __init__(self, message: str = "Google Gemini service is temporarily unreachable or unavailable."):
        super().__init__(message=message, code="AI_PROVIDER_UNAVAILABLE", status_code=503)


class AIInvalidResponseError(AIException):
    def __init__(self, message: str = "Gemini model returned an empty, blocked, or invalid response."):
        super().__init__(message=message, code="AI_INVALID_RESPONSE", status_code=502)


class AIInvalidJSONError(AIException):
    def __init__(self, message: str = "Gemini model returned malformed JSON content."):
        super().__init__(message=message, code="AI_INVALID_JSON", status_code=502)


class AISchemaValidationError(AIException):
    def __init__(self, message: str = "Gemini output failed Pydantic schema validation."):
        super().__init__(message=message, code="AI_SCHEMA_VALIDATION_FAILED", status_code=502)


class EmptyShoppingRequestError(AIException):
    def __init__(self, message: str = "Shopping request text must not be empty."):
        super().__init__(message=message, code="EMPTY_SHOPPING_REQUEST", status_code=422)


class ShoppingRequestTooLongError(AIException):
    def __init__(self, max_chars: int):
        super().__init__(
            message=f"Shopping request exceeds maximum permissible length of {max_chars} characters.",
            code="SHOPPING_REQUEST_TOO_LONG",
            status_code=413,
        )

