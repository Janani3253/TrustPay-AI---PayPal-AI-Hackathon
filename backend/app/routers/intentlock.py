"""FastAPI router for IntentLock Customer-Intent Verification Engine."""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.audit import add_audit, json_dump
from app.core.dependencies import get_current_user
from app.database import connect
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.schemas.intentlock import (
    IntentLockApproveRequest,
    IntentLockApproveResponse,
    IntentLockAuditResponse,
    IntentLockCreateRequest,
    IntentLockRecord,
    IntentLockReverifyRequest,
    IntentLockReverifyResponse,
    IntentLockVerifyRequest,
    IntentLockVerifyResponse,
)
from app.schemas.verification import BackendVerificationCheck, OverallDecision, VerificationTotals
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import cart_service
from app.services.intentlock_engine import intentlock_engine
from app.services.order_service import calculate_snapshot_hash, OrderService
from app.services.product_service import product_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IntentLock"])


def _extract_user_id(user: Any) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@router.post(
    "/intentlock/create",
    response_model=IntentLockRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a structured IntentLock purchase-intent record",
    description="Captures the customer's shopping intent, approved product, budget, and quantity.",
)
@router.post(
    "/api/intentlock/create",
    response_model=IntentLockRecord,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_intentlock_record(
    payload: IntentLockCreateRequest,
    user: User = Depends(get_current_user),
) -> IntentLockRecord:
    user_id = _extract_user_id(user)
    intent_data = payload.intent

    # If product_id specified, add to cart if cart is empty
    cart_data = await cart_service.get_cart(user_id)
    cart_items = cart_data.get("items", [])

    if payload.product_id is not None:
        # If product not in cart, add it
        has_prod = any(int(it.get("product", {}).get("id", 0)) == payload.product_id for it in cart_items)
        if not has_prod:
            await cart_service.add_item(user_id, payload.product_id, payload.quantity)
            cart_data = await cart_service.get_cart(user_id)
            cart_items = cart_data.get("items", [])

    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create purchase-intent record with an empty shopping cart. Select a product first.",
        )

    # Attach approved product details to intent
    primary_prod = cart_items[0].get("product", {})
    approved_product_id = payload.product_id or primary_prod.get("id")
    intent_data["approved_product_id"] = approved_product_id
    intent_data["product_name_and_brand"] = f"{primary_prod.get('title')} ({primary_prod.get('brand') or 'Generic'})"
    intent_data["approved_quantity"] = payload.quantity

    # Create order via OrderService
    order_dict = await OrderService.create_order(
        user_id=user_id,
        intent=intent_data,
    )
    order_id = order_dict["id"]
    order_version = order_dict["version"]
    totals = order_dict["totals"]

    original_request = intent_data.get("request", "") or intent_data.get("original_request", "")
    max_budget = float(intent_data.get("maximumBudget") or intent_data.get("max_budget") or totals.get("total", 0.0))
    currency = intent_data.get("currency") or totals.get("currency", "USD")

    add_audit(
        user_id=user_id,
        event_type="INTENTLOCK_RECORD_CREATED",
        description=f"Created IntentLock purchase intent record for order {order_id} (Max budget: ${max_budget:.2f}).",
    )

    return IntentLockRecord(
        intent_id=order_id,
        original_request=original_request,
        approved_product_id=approved_product_id,
        product_name_and_brand=intent_data.get("product_name_and_brand"),
        maximum_budget=max_budget,
        approved_quantity=payload.quantity,
        currency=currency,
        required_specifications=intent_data.get("requirements", []),
        approved_seller=intent_data.get("approved_seller"),
        customer_approval_status="PENDING",
        version=order_version,
        status=order_dict.get("status", "pending_verification"),
        totals=totals,
        items=order_dict.get("items", cart_items),
        snapshot_hash=order_dict.get("snapshot_hash", ""),
    )


@router.post(
    "/intentlock/verify",
    response_model=IntentLockVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute comprehensive IntentLock verification",
    description="Deterministic verification across Product (identity, brand, specs, substitution), Price (budget, fees), Cart (quantities, additions), and Security (prompt injection scan).",
)
@router.post(
    "/api/intentlock/verify",
    response_model=IntentLockVerifyResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def verify_intentlock(
    payload: IntentLockVerifyRequest,
    user: User = Depends(get_current_user),
) -> IntentLockVerifyResponse:
    user_id = _extract_user_id(user)

    # 1. Retrieve order and verify ownership
    order = await OrderRepository.get_by_id_and_user_id(None, payload.intent_id, user_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IntentLock record '{payload.intent_id}' not found.",
        )

    order_version = int(order.version)
    intent = order.intent_json if isinstance(order.intent_json, dict) else json.loads(order.intent_json)

    # 2. Retrieve current cart
    cart_data = await cart_service.get_cart(user_id)
    cart_items = cart_data.get("items", [])
    cart_version = cart_data.get("version", 1)

    # 3. Layered Verification
    all_checks: List[BackendVerificationCheck] = []

    # Layer A: Product Verification
    prod_summary, prod_checks = intentlock_engine.verify_product_layer(cart_items, intent)
    all_checks.extend(prod_checks)

    # Layer B: Price Verification
    totals_dict = cart_service.calculate_totals(cart_items)
    price_summary, price_checks = intentlock_engine.verify_price_layer(totals_dict, intent, cart_items)
    all_checks.extend(price_checks)

    # Layer C: Cart Verification
    cart_summary, cart_checks = intentlock_engine.verify_cart_layer(cart_items, intent, order_version, cart_version)
    all_checks.extend(cart_checks)

    # Layer D: Security Verification
    sec_summary, sec_checks = intentlock_engine.verify_security_layer(cart_items)
    all_checks.extend(sec_checks)

    # Determine Overall Decision
    has_critical_failure = any(c.status == "Failed" and c.critical for c in all_checks)
    has_warning = any(c.status == "Needs Review" for c in all_checks)

    if has_critical_failure:
        overall_status = "Failed"
        decision = "BLOCKED"
    elif has_warning:
        overall_status = "Needs Review"
        decision = "NEEDS_REVIEW"
    else:
        overall_status = "Passed"
        decision = "READY_FOR_APPROVAL"

    # 4. Update order state in database
    new_status = "verified" if overall_status == "Passed" else "verification_failed"
    checks_dict = {
        "status": overall_status,
        "decision": decision,
        "checks": [c.model_dump() for c in all_checks],
    }

    try:
        await OrderRepository.update_order(
            None,
            order,
            status=new_status,
            checks_json=checks_dict,
        )
    except Exception as exc:
        logger.error("Failed to update order status in PostgreSQL: %s", exc)

    # Update SQLite mirror as well
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE orders SET status = ?, checks_json = ? WHERE id = ?",
                (new_status, json.dumps(checks_dict), payload.intent_id),
            )
    except Exception:
        pass

    add_audit(
        user_id=user_id,
        event_type="INTENTLOCK_VERIFICATION_EVALUATED",
        description=f"IntentLock verified record {payload.intent_id}: Status={overall_status}, Decision={decision}.",
    )

    return IntentLockVerifyResponse(
        intent_id=payload.intent_id,
        version=order_version,
        status=overall_status,
        decision=decision,
        product_verification=prod_summary,
        price_verification=price_summary,
        cart_verification=cart_summary,
        website_security_verification=sec_summary,
        checks=all_checks,
        totals=VerificationTotals(**totals_dict),
    )


@router.post(
    "/intentlock/approve",
    response_model=IntentLockApproveResponse,
    status_code=status.HTTP_200_OK,
    summary="Record customer explicit approval for verified IntentLock purchase",
    description="Validates that server verification passed and cart is intact, then records cryptographic approval snapshot.",
)
@router.post(
    "/api/intentlock/approve",
    response_model=IntentLockApproveResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def approve_intentlock(
    payload: IntentLockApproveRequest,
    user: User = Depends(get_current_user),
) -> IntentLockApproveResponse:
    user_id = _extract_user_id(user)
    result = await ApprovalService.approve_order(
        order_id=payload.intent_id,
        order_version=payload.version,
        user_id=user_id,
    )

    # Fetch order to obtain snapshot hash
    order = await OrderRepository.get_by_id_and_user_id(None, payload.intent_id, user_id)
    snapshot_hash = getattr(order, "snapshot_hash", "") if order else ""

    add_audit(
        user_id=user_id,
        event_type="INTENTLOCK_CUSTOMER_APPROVED",
        description=f"Customer explicitly approved IntentLock purchase {payload.intent_id} (Version {payload.version}).",
    )

    return IntentLockApproveResponse(
        intent_id=payload.intent_id,
        version=payload.version,
        status="approved",
        approved_at=result.get("approved_at", ""),
        snapshot_hash=snapshot_hash,
    )


@router.post(
    "/intentlock/reverify",
    response_model=IntentLockReverifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Immediate pre-checkout revalidation (Layer E: Payment Verification)",
    description="Revalidates complete cart immediately before payment. Blocks checkout if cart or price mutated since approval.",
)
@router.post(
    "/api/intentlock/reverify",
    response_model=IntentLockReverifyResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def reverify_intentlock_before_payment(
    payload: IntentLockReverifyRequest,
    user: User = Depends(get_current_user),
) -> IntentLockReverifyResponse:
    user_id = _extract_user_id(user)

    # 1. Fetch order
    order = await OrderRepository.get_by_id_and_user_id(None, payload.intent_id, user_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IntentLock record '{payload.intent_id}' not found.",
        )

    # 2. Fetch current cart
    cart_data = await cart_service.get_cart(user_id)
    current_items = cart_data.get("items", [])
    current_totals = cart_service.calculate_totals(current_items)

    # 3. Deterministic reverification
    passed, reason = intentlock_engine.reverify_for_payment(order, current_items, current_totals)

    approved_total = float(order.total)
    current_total = float(current_totals.get("total", 0.0))

    if not passed:
        # Invalidate approval whenever purchase details change
        try:
            await OrderRepository.update_order(None, order, status="verification_failed")
            with connect() as conn:
                conn.execute("UPDATE orders SET status = 'verification_failed' WHERE id = ?", (payload.intent_id,))
        except Exception:
            pass

        add_audit(
            user_id=user_id,
            event_type="INTENTLOCK_REVERIFICATION_BLOCKED",
            description=f"Pre-payment reverification blocked for {payload.intent_id}: {reason}",
        )

        return IntentLockReverifyResponse(
            intent_id=payload.intent_id,
            reverification_passed=False,
            payment_allowed=False,
            status="BLOCKED",
            reason=reason,
            current_cart_total=current_total,
            approved_total=approved_total,
            currency=order.currency,
            reverified_at=datetime.now(timezone.utc).isoformat(),
        )

    add_audit(
        user_id=user_id,
        event_type="INTENTLOCK_REVERIFICATION_PASSED",
        description=f"Pre-payment reverification passed for {payload.intent_id}. Cart matches approved snapshot.",
    )

    return IntentLockReverifyResponse(
        intent_id=payload.intent_id,
        reverification_passed=True,
        payment_allowed=True,
        status="ALLOWED",
        reason="Purchase conditions strictly match approved customer intent. Checkout authorized.",
        current_cart_total=current_total,
        approved_total=approved_total,
        currency=order.currency,
        reverified_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/intentlock/audit/{intent_id}",
    response_model=IntentLockAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Get cryptographic SHA-256 tamper-evident audit log for purchase intent",
    description="Returns the chained cryptographic audit trail protecting purchase intent integrity.",
)
@router.get(
    "/api/intentlock/audit/{intent_id}",
    response_model=IntentLockAuditResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_intentlock_audit_log(
    intent_id: str,
    user: User = Depends(get_current_user),
) -> IntentLockAuditResponse:
    user_id = _extract_user_id(user)

    # Retrieve all audit records for this user
    events = AuditService.get_audit_trail(user_id)
    # Filter events related to this intent or return all
    intent_events = [e for e in events if intent_id in str(e.get("description", "")) or e.get("order_id") == intent_id]
    if not intent_events:
        intent_events = events

    # Check chain integrity
    integrity_result = AuditService.verify_chain_integrity(user_id)

    return IntentLockAuditResponse(
        intent_id=intent_id,
        chain_valid=integrity_result.get("valid", True),
        records_count=len(intent_events),
        events=intent_events,
    )
