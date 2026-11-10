import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.audit import add_audit
from app.core.dependencies import get_current_user
from app.models.user import User
from app.providers.exceptions import (
    InvalidProductIdError,
    ProductNotFoundError,
    ProductProviderException,
    UnsupportedProviderError,
)
from app.schemas.security import (
    ContentScanRequest,
    ContentScanResponse,
    ProductSecurityScanRequest,
    ProductSecurityScanResponse,
)
from app.services.product_service import product_service
from app.services.prompt_injection_service import prompt_injection_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Security"])


@router.post(
    "/security/analyze-product",
    response_model=ProductSecurityScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Scan product content for prompt injection and untrusted content risks",
    description=(
        "Retrieves the product via backend-controlled provider, sanitizes and inspects "
        "its metadata using deterministic rules and optional Gemini AI analysis, and returns "
        "the security assessment."
    ),
)
@router.post(
    "/api/security/analyze-product",
    response_model=ProductSecurityScanResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def analyze_product(
    payload: ProductSecurityScanRequest,
    user: User = Depends(get_current_user),
) -> ProductSecurityScanResponse:
    """
    Perform prompt injection scan on authentic product data retrieved from catalog.
    Prevents client-side content tampering.
    """
    user_id = user["id"] if isinstance(user, dict) else user.id

    # 1. Fetch genuine product data from provider
    try:
        product = await product_service.get_product_details(
            product_id=payload.product_id,
            platform_id=payload.provider,
        )
    except ProductNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {payload.product_id} was not found on provider '{payload.provider}'.",
        ) from err
    except (InvalidProductIdError, UnsupportedProviderError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err.message if hasattr(err, "message") else err),
        ) from err
    except ProductProviderException as err:
        raise HTTPException(
            status_code=err.status_code,
            detail=err.message,
        ) from err
    except Exception as exc:
        logger.error("Unexpected error fetching product for security scan: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve product details from upstream catalog.",
        ) from exc

    # 2. Convert to dictionary
    if hasattr(product, "model_dump"):
        product_dict = product.model_dump()
    elif isinstance(product, dict):
        product_dict = product
    else:
        product_dict = dict(product)
    product_dict["provider"] = payload.provider

    # 3. Perform security analysis
    try:
        scan_result = await prompt_injection_service.analyze_product(
            product=product_dict,
            analysis_mode=payload.analysis_mode,
        )
    except Exception as exc:
        logger.error("Security scan execution failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Security scan failed: {exc}",
        ) from exc

    # 4. Audit logging
    add_audit(
        user_id=user_id,
        event_type="SECURITY_PRODUCT_SCAN",
        description=(
            f"Product {payload.product_id} ({payload.provider}) scanned. "
            f"Risk: {scan_result.risk_level.value}, Detected: {scan_result.detected}, "
            f"Findings: {len(scan_result.findings)}"
        ),
    )

    return scan_result


@router.post(
    "/security/scan-content",
    response_model=ContentScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Scan untrusted shopping website content for prompt injection",
    description="Analyzes untrusted product descriptions, reviews, or seller text for prompt injection attacks and malicious directives.",
)
@router.post(
    "/api/security/scan-content",
    response_model=ContentScanResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def scan_untrusted_content(
    payload: ContentScanRequest,
    user: User = Depends(get_current_user),
) -> ContentScanResponse:
    user_id = user["id"] if isinstance(user, dict) else user.id
    try:
        scan_result = await prompt_injection_service.scan_content(
            content=payload.content,
            product_id=payload.product_id,
            source=payload.source or "shopping_website",
        )
        add_audit(
            user_id=user_id,
            event_type="SECURITY_PROMPT_INJECTION_SCAN",
            description=(
                f"Scanned untrusted content. Risk: {scan_result.risk_level.value}, "
                f"Suspicious: {scan_result.is_suspicious}, Action: {scan_result.action.value}, "
                f"Patterns: {', '.join(scan_result.detected_patterns) or 'none'}."
            ),
        )
        return scan_result
    except Exception as exc:
        logger.error("Content security scan failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Security scan failed: {exc}",
        ) from exc
