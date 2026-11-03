from typing import Optional


class ProductProviderException(Exception):
    """Base exception for all product provider operations."""

    def __init__(self, message: str, code: str = "PRODUCT_PROVIDER_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ProductNotFoundError(ProductProviderException):
    def __init__(self, product_id: int | str):
        super().__init__(
            message=f"Product with ID {product_id} was not found.",
            code="PRODUCT_NOT_FOUND",
            status_code=404,
        )
        self.product_id = product_id


class InvalidProductIdError(ProductProviderException):
    def __init__(self, message: str = "Invalid product ID format. ID must be a positive integer."):
        super().__init__(
            message=message,
            code="INVALID_PRODUCT_ID",
            status_code=422,
        )


class InvalidSearchQueryError(ProductProviderException):
    def __init__(self, message: str = "Search query must not be empty."):
        super().__init__(
            message=message,
            code="INVALID_SEARCH_QUERY",
            status_code=422,
        )


class InvalidPaginationError(ProductProviderException):
    def __init__(self, message: str = "Pagination parameters (limit, skip) are invalid."):
        super().__init__(
            message=message,
            code="INVALID_PAGINATION",
            status_code=422,
        )


class ProviderUnavailableError(ProductProviderException):
    def __init__(self, message: str = "The product provider is temporarily unavailable."):
        super().__init__(
            message=message,
            code="PRODUCT_PROVIDER_UNAVAILABLE",
            status_code=503,
        )


class ProviderTimeoutError(ProductProviderException):
    def __init__(self, message: str = "The product provider timed out while processing the request."):
        super().__init__(
            message=message,
            code="PRODUCT_PROVIDER_TIMEOUT",
            status_code=504,
        )


class InvalidProviderResponseError(ProductProviderException):
    def __init__(self, message: str = "The product provider returned a malformed or invalid response."):
        super().__init__(
            message=message,
            code="INVALID_PROVIDER_RESPONSE",
            status_code=502,
        )


class UnsupportedProviderError(ProductProviderException):
    def __init__(self, provider_id: str):
        super().__init__(
            message=f"Shopping platform '{provider_id}' is not supported or not configured.",
            code="UNSUPPORTED_PROVIDER",
            status_code=400,
        )
        self.provider_id = provider_id


class ProviderNotConfiguredError(ProductProviderException):
    def __init__(self, provider_id: str):
        super().__init__(
            message=f"Platform '{provider_id}' integration is not configured.",
            code="PROVIDER_NOT_CONFIGURED",
            status_code=503,
        )
        self.provider_id = provider_id

