import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .database import connect, initialize_database
from .schemas import (
    ApprovalRequest,
    AuthResponse,
    CartItemRequest,
    CartQuantityRequest,
    IntentRequest,
    LoginRequest,
    OrderRequest,
    PayPalCaptureRequest,
    RegisterRequest,
    UserResponse,
    VerifyOrderRequest,
)

DUMMYJSON_BASE_URL = os.getenv("DUMMYJSON_BASE_URL", "https://dummyjson.com").rstrip("/")
PAYPAL_API_BASE_URL = os.getenv("PAYPAL_API_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
_paypal_api_url = urlparse(PAYPAL_API_BASE_URL)
if (
    _paypal_api_url.scheme != "https"
    or _paypal_api_url.hostname != "api-m.sandbox.paypal.com"
    or _paypal_api_url.port not in (None, 443)
    or _paypal_api_url.username is not None
    or _paypal_api_url.password is not None
    or _paypal_api_url.path not in ("", "/")
    or _paypal_api_url.query
    or _paypal_api_url.fragment
):
    raise RuntimeError(
        "PAYPAL_API_BASE_URL must be https://api-m.sandbox.paypal.com; live PayPal is not supported."
    )
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
SECRET_KEY = os.getenv("TRUSTPAY_SECRET_KEY", "local-development-key-change-before-deployment")
TOKEN_TTL_SECONDS = 60 * 60 * 8
FEE_SHIPPING = 9.99
FEE_TAX_RATE = 0.05

app = FastAPI(title="TrustPay AI IntentLock API", version="0.1.0")
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "TRUSTPAY_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(derived).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_text, expected_text = stored_hash.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def create_token(user_id: int) -> str:
    header = b64url(json_dump({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json_dump({
        "sub": str(user_id),
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)).timestamp()),
    }).encode())
    message = f"{header}.{payload}".encode()
    signature = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64url(signature)}"


def decode_token(token: str) -> int:
    try:
        header, payload, signature = token.split(".")
        header_value = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
        if header_value.get("alg") != "HS256" or header_value.get("typ") != "JWT":
            raise ValueError("Unsupported token header")
        message = f"{header}.{payload}".encode()
        expected = b64url(hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(decoded["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Expired token")
        return int(decoded["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token.") from error


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer access token is required.")
    user_id = decode_token(authorization.removeprefix("Bearer ").strip())
    with connect() as connection:
        user = connection.execute(
            "SELECT id, name, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account no longer exists.")
    return dict(user)


def add_audit(
    user_id: int,
    event_type: str,
    description: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    event_id = str(uuid.uuid4())
    timestamp = utc_now()

    def insert_event(db: sqlite3.Connection) -> None:
        previous = db.execute(
            "SELECT hash FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        previous_hash = previous["hash"] if previous else "GENESIS"
        payload = {"id": event_id, "type": event_type, "timestamp": timestamp, "description": description}
        digest = hashlib.sha256(f"{previous_hash}:{json_dump(payload)}".encode()).hexdigest()
        db.execute(
            """INSERT INTO audit_events
               (id, user_id, type, timestamp, description, previous_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, event_type, timestamp, description, previous_hash, digest),
        )

    if connection is not None:
        insert_event(connection)
        return
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        insert_event(db)


async def dummyjson_get(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{DUMMYJSON_BASE_URL}{path}", params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue service is currently unavailable.",
        ) from error


async def fetch_product(product_id: int) -> dict[str, Any]:
    product = await dummyjson_get(f"/products/{product_id}")
    if not isinstance(product, dict) or product.get("id") != product_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Product catalogue returned an invalid product.")
    return product


async def current_cart(user_id: int) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT product_id, quantity FROM cart_items WHERE user_id = ? ORDER BY product_id",
            (user_id,),
        ).fetchall()
    products = await asyncio.gather(*(fetch_product(row["product_id"]) for row in rows))
    return [
        {"product": product, "quantity": row["quantity"]}
        for row, product in zip(rows, products, strict=True)
    ]


def cart_price(items: list[dict[str, Any]]) -> dict[str, Any]:
    subtotal = sum(float(item["product"]["price"]) * int(item["quantity"]) for item in items)
    shipping = FEE_SHIPPING if subtotal else 0
    tax = round(subtotal * FEE_TAX_RATE + 1e-9, 2)
    return {
        "subtotal": round(subtotal, 2),
        "shipping": shipping,
        "tax": tax,
        "total": round(subtotal + shipping + tax, 2),
        "currency": "USD",
    }


def parse_intent(payload: IntentRequest) -> dict[str, Any]:
    text = payload.request
    lowered = text.lower()
    requirements = []
    for pattern, label in [
        (r"(\d+\s?gb)\s?ram", "RAM"),
        (r"(\d+\s?gb\s?(?:ssd|storage))", "Storage"),
        (r"\b((?:intel\s*)?i[3579])\b", "Processor"),
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            requirements.append({"name": label, "value": match.group(1)})
    inferred_category = ""
    for pattern, category in [
        (r"\b(laptop|notebook|computer)\b", "laptops"),
        (r"\b(phone|mobile|smartphone)\b", "smartphones"),
        (r"\btablet\b", "tablets"),
        (r"\bwatch\b", "mens-watches"),
        (r"\b(shoe|sneaker)\b", "mens-shoes"),
        (r"\b(shirt|dress|clothing)\b", "womens-dresses"),
    ]:
        if re.search(pattern, lowered):
            inferred_category = category
            break
    budget_match = re.search(
        r"(?:under|below|less than|maximum|max|budget(?: of)?|up to)\s*(?:₹|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?",
        text,
        re.IGNORECASE,
    )
    budget = payload.maximumBudget
    if budget_match:
        parsed = float(budget_match.group(1).replace(",", ""))
        budget = parsed * (1000 if budget_match.group(2) else 1)
    currency = payload.currency
    if re.search(r"\$|usd|dollars?", text, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"₹|inr|rupees?", text, re.IGNORECASE):
        currency = "INR"
    return {
        "request": text,
        "category": payload.category or inferred_category,
        "requirements": requirements,
        "maximumBudget": budget,
        "currency": currency,
        "trustedSellersOnly": payload.trustedSellersOnly,
        "platformId": payload.platformId,
        "excludeAccessories": bool(re.search(r"\b(?:do not|don't|no)\s+add\s+accessories\b", lowered)),
    }


def build_verification(items: list[dict[str, Any]], intent: dict[str, Any], order_version: int) -> dict[str, Any]:
    totals = cart_price(items)
    categories = {item["product"].get("category", "") for item in items}
    requirements = intent.get("requirements", [])
    category_ok = not intent.get("category") or categories == {intent["category"]}
    accessory_items = [
        item["product"].get("title", "")
        for item in items
        if re.search(r"\b(accessory|accessories|case|charger|cable|adapter)\b", item["product"].get("title", ""), re.I)
    ]
    currency_ok = intent.get("currency") == totals["currency"]
    checks = [
        {
            "name": "Product type",
            "status": "Passed" if category_ok else "Failed",
            "reason": "Cart product category matches the purchase policy." if category_ok else "One or more products do not match the requested product category.",
            "critical": True,
        },
        {
            "name": "Product specifications",
            "status": "Needs Review" if requirements else "Needs Review",
            "reason": "Requested technical specifications are not available in the public product catalogue and cannot be verified.",
            "critical": False,
        },
        {
            "name": "Quantity",
            "status": "Passed" if items and all(int(item["quantity"]) > 0 for item in items) else "Failed",
            "reason": "Each cart quantity is a positive integer." if items else "The cart is empty.",
            "critical": True,
        },
        {
            "name": "Seller requirements",
            "status": "Failed" if intent.get("trustedSellersOnly") else "Needs Review",
            "reason": "Seller identity and trust status are not supplied by the catalogue; the required seller policy cannot be met." if intent.get("trustedSellersOnly") else "Seller identity and trust status are not supplied by the catalogue.",
            "critical": bool(intent.get("trustedSellersOnly")),
        },
        {
            "name": "Unauthorized additions",
            "status": "Failed" if intent.get("excludeAccessories") and accessory_items else "Passed",
            "reason": f"Unrequested accessory detected: {', '.join(accessory_items)}." if accessory_items and intent.get("excludeAccessories") else "No excluded accessory was detected in the cart.",
            "critical": True,
        },
        {
            "name": "Shipping and additional fees",
            "status": "Passed",
            "reason": f"Estimated shipping (${totals['shipping']:.2f}) and tax (${totals['tax']:.2f}) are itemized; estimates are demo calculations.",
            "critical": False,
        },
        {
            "name": "Final price",
            "status": "Failed" if not currency_ok or totals["total"] > float(intent.get("maximumBudget", 0)) else "Passed",
            "reason": (
                f"Budget is {intent.get('currency')}, but catalogue prices are {totals['currency']}; no conversion is assumed."
                if not currency_ok
                else f"Estimated total ${totals['total']:.2f} exceeds the ${float(intent.get('maximumBudget', 0)):.2f} budget."
                if totals["total"] > float(intent.get("maximumBudget", 0))
                else f"Estimated total ${totals['total']:.2f} is within the stated budget."
            ),
            "critical": True,
        },
        {
            "name": "Suspicious content",
            "status": "Needs Review",
            "reason": "Product descriptions are untrusted external text. They are not executed or allowed to override the purchase policy.",
            "critical": False,
        },
    ]
    failed_critical = any(check["critical"] and check["status"] == "Failed" for check in checks)
    return {
        "status": "Failed" if failed_critical else "Passed",
        "checks": checks,
        "order_version": order_version,
        "totals": totals,
    }


def require_order(connection: Any, order_id: str, user_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order was not found.")
    return row


def order_matches_cart(order: Any, items: list[dict[str, Any]]) -> bool:
    stored = json.loads(order["cart_json"])
    return json_dump(stored) == json_dump(items)


async def paypal_access_token() -> str:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    if not client_id.strip() or not client_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PayPal Sandbox is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET on the backend.",
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{PAYPAL_API_BASE_URL}/v1/oauth2/token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to PayPal Sandbox authentication.",
        ) from error

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox rejected the backend credentials.",
        )
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not authenticate with PayPal Sandbox.",
        )
    try:
        token_response = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox returned an invalid authentication response.",
        ) from error
    access_token = token_response.get("access_token") if isinstance(token_response, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox returned an invalid authentication response.",
        )
    return access_token


class PayPalTransportError(Exception):
    pass


async def paypal_api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    access_token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    token = access_token or await paypal_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if request_id:
        headers["PayPal-Request-Id"] = request_id

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.request(
                    method,
                    f"{PAYPAL_API_BASE_URL}{path}",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as error:
            raise PayPalTransportError from error

        if response.status_code == status.HTTP_401_UNAUTHORIZED and attempt == 0:
            token = await paypal_access_token()
            headers["Authorization"] = f"Bearer {token}"
            continue

        try:
            body = response.json()
        except ValueError as error:
            if response.is_success:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal Sandbox returned an invalid response.",
                ) from error
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="PayPal Sandbox returned an invalid response.",
            )
        return response.status_code, body

    raise PayPalTransportError("PayPal authentication could not be refreshed.")


def payment_request_id(action: str, order_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"trustpay:{action}:{order_id}"))


def validate_paypal_purchase_unit(
    paypal_order: dict[str, Any],
    order: Any,
    paypal_order_id: str | None = None,
) -> dict[str, Any]:
    if paypal_order_id is not None and paypal_order.get("id") != paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal returned a different order than the one approved.",
        )
    purchase_units = paypal_order.get("purchase_units")
    if not isinstance(purchase_units, list) or len(purchase_units) != 1:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an unexpected number of purchase units.",
        )
    purchase_unit = purchase_units[0]
    if not isinstance(purchase_unit, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid purchase unit.",
        )
    if purchase_unit.get("reference_id") != order["id"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal purchase reference does not match the approved TrustPay order.",
        )

    amount = purchase_unit.get("amount")
    if not isinstance(amount, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid order amount.",
        )
    try:
        expected_amount = Decimal(str(order["total"])).quantize(Decimal("0.01"))
        actual_amount = Decimal(str(amount.get("value", "")))
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid order amount.",
        )
    if not actual_amount.is_finite() or actual_amount != expected_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal order amount does not match the approved TrustPay order.",
        )
    if amount.get("currency_code") != order["currency"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal order currency does not match the approved TrustPay order.",
        )
    return purchase_unit


def paypal_create_response_needs_refresh(paypal_order: dict[str, Any]) -> bool:
    purchase_units = paypal_order.get("purchase_units")
    if not isinstance(purchase_units, list) or not purchase_units:
        return True
    if len(purchase_units) != 1 or not isinstance(purchase_units[0], dict):
        return False

    purchase_unit = purchase_units[0]
    amount = purchase_unit.get("amount")
    if (
        "reference_id" not in purchase_unit
        or not isinstance(amount, dict)
        or "value" not in amount
        or "currency_code" not in amount
    ):
        return True

    links = paypal_order.get("links")
    has_approval_link = isinstance(links, list) and any(
        isinstance(link, dict)
        and link.get("rel") in {"approve", "payer-action"}
        and isinstance(link.get("href"), str)
        and link["href"]
        for link in links
    )
    return paypal_order.get("status") is None or not has_approval_link


def paypal_approval_url(paypal_order: dict[str, Any]) -> str:
    links = paypal_order.get("links")
    if not isinstance(links, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox did not return an approval URL.",
        )
    approval_url = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}
        ),
        None,
    )
    try:
        parsed_url = urlparse(approval_url) if isinstance(approval_url, str) else None
        allowed_port = parsed_url is not None and parsed_url.port in (None, 443)
    except ValueError:
        parsed_url = None
        allowed_port = False
    if (
        parsed_url is None
        or parsed_url.scheme != "https"
        or not allowed_port
        or parsed_url.hostname is None
        or not (
            parsed_url.hostname == "sandbox.paypal.com"
            or parsed_url.hostname.endswith(".sandbox.paypal.com")
        )
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox returned an invalid approval URL.",
        )
    return approval_url


def validate_paypal_capture(
    paypal_order: dict[str, Any],
    order: Any,
    paypal_order_id: str,
) -> tuple[str, Decimal, str]:
    if paypal_order.get("id") != paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal returned a different order than the one approved.",
        )
    if paypal_order.get("status") != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal has not confirmed a completed payment.",
        )
    purchase_unit = validate_paypal_purchase_unit(paypal_order, order)
    payments = purchase_unit.get("payments")
    captures = payments.get("captures") if isinstance(payments, dict) else None
    if not isinstance(captures, list) or len(captures) != 1 or not isinstance(captures[0], dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal did not return exactly one payment capture.",
        )

    capture = captures[0]
    capture_id = capture.get("id")
    if capture.get("status") != "COMPLETED" or not isinstance(capture_id, str) or not capture_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal did not confirm a completed capture.",
        )
    if capture.get("final_capture") is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PayPal returned a partial capture for the approved order.",
        )
    capture_amount = capture.get("amount")
    if not isinstance(capture_amount, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid capture amount.",
        )
    try:
        expected_amount = Decimal(str(order["total"])).quantize(Decimal("0.01"))
        actual_amount = Decimal(str(capture_amount.get("value", "")))
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid capture amount.",
        )
    currency = capture_amount.get("currency_code")
    if not actual_amount.is_finite() or actual_amount != expected_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Captured amount does not match the customer-approved order amount.",
        )
    if currency != order["currency"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Captured currency does not match the customer-approved order currency.",
        )
    return capture_id, actual_amount, currency


def payment_pending_response(order: Any) -> dict[str, Any]:
    return {
        "id": None,
        "order_id": order["id"],
        "paypal_reference": None,
        "amount": order["total"],
        "currency": order["currency"],
        "date": datetime.now(timezone.utc).date().isoformat(),
        "status": "PENDING",
        "method": "PayPal Sandbox",
    }


def set_payment_status(order_id: str, user_id: int, next_status: str) -> None:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = require_order(connection, order_id, user_id)
        if order["status"] != "completed":
            connection.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (next_status, utc_now(), order_id, user_id),
            )


def audit_paypal_validation_error(user_id: int, order_id: str, error: HTTPException) -> None:
    detail = error.detail.lower() if isinstance(error.detail, str) else ""
    if "currency" in detail:
        event_type = "Payment currency mismatch detected"
    elif "amount" in detail:
        event_type = "Payment amount mismatch detected"
    else:
        event_type = "Payment reconciliation required"
    add_audit(
        user_id,
        event_type,
        f"PayPal response validation failed for TrustPay order {order_id}.",
    )


def clear_cart_if_matches_order(connection: sqlite3.Connection, order: Any) -> bool:
    stored_items = json.loads(order["cart_json"])
    expected = sorted(
        (int(item["product"]["id"]), int(item["quantity"]))
        for item in stored_items
    )
    if not expected:
        return False
    current = sorted(
        (int(row["product_id"]), int(row["quantity"]))
        for row in connection.execute(
            "SELECT product_id, quantity FROM cart_items WHERE user_id = ?",
            (order["user_id"],),
        )
    )
    if current != expected:
        return False
    connection.execute("DELETE FROM cart_items WHERE user_id = ?", (order["user_id"],))
    return True


def record_completed_payment(
    order: Any,
    user_id: int,
    paypal_order_id: str,
    capture_id: str,
    amount: Decimal,
    currency: str,
) -> dict[str, Any]:
    transaction_date = datetime.now(timezone.utc).date().isoformat()
    transaction_id = f"TRX-{uuid.uuid4().hex[:12].upper()}"
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest_order = require_order(connection, order["id"], user_id)
        if latest_order["paypal_order_id"] != paypal_order_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal order no longer matches the TrustPay order.",
            )
        existing = connection.execute(
            "SELECT * FROM transactions WHERE order_id = ? AND user_id = ?",
            (order["id"], user_id),
        ).fetchone()
        if existing:
            if (
                latest_order["status"] != "completed"
                or existing["paypal_reference"] != capture_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A different payment is already recorded for this TrustPay order.",
                )
            return {
                "id": existing["id"],
                "order_id": existing["order_id"],
                "paypal_reference": existing["paypal_reference"],
                "amount": existing["amount"],
                "currency": existing["currency"],
                "date": existing["date"],
                "status": "COMPLETED",
                "method": existing["method"],
                "product": existing["product"],
                "cart_cleared": False,
            }
        if latest_order["status"] not in {
            "paypal_capturing",
            "paypal_reconciling",
            "reconciliation_required",
            "paypal_pending",
            "cancelled",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TrustPay order is not eligible for payment completion.",
            )

        stored_items = json.loads(latest_order["cart_json"])
        product_names = ", ".join(
            item["product"].get("title", "Product") for item in stored_items
        )
        connection.execute(
            """
            INSERT INTO transactions
            (id, user_id, order_id, product, amount, currency, date, method, status, verification, paypal_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                user_id,
                order["id"],
                product_names,
                float(amount),
                currency,
                transaction_date,
                "PayPal Sandbox",
                "Completed",
                "Backend verified",
                capture_id,
            ),
        )
        connection.execute(
            """
            UPDATE orders
            SET status = 'completed', paypal_capture_id = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (capture_id, utc_now(), order["id"], user_id),
        )
        cart_cleared = clear_cart_if_matches_order(connection, latest_order)

    add_audit(
        user_id,
        "Sandbox payment completed",
        f"PayPal Sandbox capture verified for order {order['id']}.",
    )
    return {
        "id": transaction_id,
        "order_id": order["id"],
        "paypal_reference": capture_id,
        "amount": float(amount),
        "currency": currency,
        "date": transaction_date,
        "status": "COMPLETED",
        "method": "PayPal Sandbox",
        "product": product_names,
        "cart_cleared": cart_cleared,
    }


async def reconcile_paypal_order(
    order: Any,
    user_id: int,
    paypal_order_id: str,
    access_token: str,
    *,
    cancel_if_unpaid: bool = False,
) -> dict[str, Any]:
    try:
        response_status, paypal_order = await paypal_api_request(
            "GET",
            f"/v2/checkout/orders/{quote(paypal_order_id, safe='')}",
            access_token=access_token,
        )
    except (PayPalTransportError, HTTPException) as error:
        set_payment_status(order["id"], user_id, "reconciliation_required")
        add_audit(
            user_id,
            "Payment reconciliation required",
            f"PayPal status could not be confirmed for TrustPay order {order['id']}.",
        )
        return payment_pending_response(order)

    if response_status != status.HTTP_200_OK:
        set_payment_status(order["id"], user_id, "reconciliation_required")
        add_audit(
            user_id,
            "Payment reconciliation required",
            f"PayPal status could not be confirmed for TrustPay order {order['id']}.",
        )
        return payment_pending_response(order)

    paypal_status = paypal_order.get("status")
    if paypal_status == "COMPLETED":
        try:
            capture_id, amount, currency = validate_paypal_capture(
                paypal_order,
                order,
                paypal_order_id,
            )
        except HTTPException as error:
            set_payment_status(order["id"], user_id, "reconciliation_required")
            audit_paypal_validation_error(user_id, order["id"], error)
            raise
        return record_completed_payment(
            order,
            user_id,
            paypal_order_id,
            capture_id,
            amount,
            currency,
        )

    if paypal_status in {"VOIDED", "CANCELLED"}:
        set_payment_status(order["id"], user_id, "cancelled")
        add_audit(
            user_id,
            "Sandbox payment cancelled",
            f"PayPal reported a cancelled order for TrustPay order {order['id']}.",
        )
        response = payment_pending_response(order)
        response["status"] = "CANCELLED"
        return response

    purchase_units = paypal_order.get("purchase_units")
    if isinstance(purchase_units, list):
        failed_capture = any(
            capture.get("status") in {"DECLINED", "FAILED"}
            for unit in purchase_units
            if isinstance(unit, dict)
            and isinstance(unit.get("payments"), dict)
            and isinstance(unit["payments"].get("captures"), list)
            for capture in unit["payments"]["captures"]
            if isinstance(capture, dict)
        )
        if failed_capture or paypal_status == "DENIED":
            set_payment_status(order["id"], user_id, "failed")
            add_audit(
                user_id,
                "Sandbox payment failed",
                f"PayPal reported a failed payment for TrustPay order {order['id']}.",
            )
            response = payment_pending_response(order)
            response["status"] = "FAILED"
            return response

    if paypal_status in {"APPROVED", "CREATED"} and cancel_if_unpaid:
        set_payment_status(order["id"], user_id, "cancelled")
        add_audit(
            user_id,
            "Sandbox payment cancelled",
            f"Customer cancelled TrustPay order {order['id']} before capture.",
        )
        response = payment_pending_response(order)
        response["status"] = "CANCELLED"
        return response

    if paypal_status == "APPROVED":
        set_payment_status(order["id"], user_id, "paypal_pending")
    else:
        set_payment_status(order["id"], user_id, "reconciliation_required")
        add_audit(
            user_id,
            "Payment reconciliation required",
            f"PayPal returned an unconfirmed status for TrustPay order {order['id']}.",
        )
    return payment_pending_response(order)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> dict[str, Any]:
    with connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (payload.name.strip(), payload.email.lower(), make_password_hash(payload.password), utc_now()),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.") from error
        user = {"id": cursor.lastrowid, "name": payload.name.strip(), "email": payload.email.lower()}
    add_audit(int(user["id"]), "Account registered", "Created a customer account.")
    return {"access_token": create_token(int(user["id"])), "user": user}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> dict[str, Any]:
    with connect() as connection:
        user = connection.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (payload.email.lower(),),
        ).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    public_user = {"id": user["id"], "name": user["name"], "email": user["email"]}
    add_audit(int(user["id"]), "User signed in", "Authenticated a customer session.")
    return {"access_token": create_token(user["id"]), "user": public_user}


@app.get("/api/auth/me", response_model=UserResponse)
def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@app.get("/api/platforms")
def platforms(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [
        {
            "id": "dummyjson",
            "name": "DummyJSON Demo Store",
            "supported": True,
            "demo_only": True,
            "description": "Catalogue browsing and product details are provided by DummyJSON.",
        },
        *[
            {
                "id": platform,
                "name": platform,
                "supported": False,
                "demo_only": False,
                "description": "Direct shopping integration is not configured for this platform.",
            }
            for platform in ("Amazon", "Flipkart", "Myntra")
        ],
    ]


@app.post("/api/intent/parse")
def intent_parse(payload: IntentRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if payload.platformId != "dummyjson":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only the DummyJSON Demo Store is supported.")
    intent = parse_intent(payload)
    add_audit(user["id"], "Purchase policy created", "Created a purchase policy through the backend intent parser.")
    return intent


@app.get("/api/products")
async def list_products(
    q: str | None = None,
    category: str | None = None,
    limit: int = 200,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="limit must be between 1 and 200.")
    if q and q.strip():
        return await dummyjson_get("/products/search", {"q": q.strip(), "limit": limit})
    if category:
        if not re.fullmatch(r"[a-z0-9-]{1,80}", category):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product category.")
        return await dummyjson_get(f"/products/category/{quote(category, safe='')}", {"limit": limit})
    return await dummyjson_get("/products", {"limit": limit})


@app.get("/api/products/categories")
async def list_categories(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    result = await dummyjson_get("/products/categories")
    return [
        {"slug": item, "name": item.replace("-", " ").title(), "url": ""}
        if isinstance(item, str)
        else item
        for item in result
    ]


@app.get("/api/products/{product_id}")
async def product_details(product_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return await fetch_product(product_id)


@app.post("/api/recommendations/search")
async def recommendations(
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    intent = payload.get("intent")
    if not isinstance(intent, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An intent object is required.")
    category = intent.get("category")
    query = intent.get("request", "").strip()
    if category:
        if not isinstance(category, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", category):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product category.")
        result = await dummyjson_get(f"/products/category/{quote(category, safe='')}", {"limit": 200})
    else:
        result = await dummyjson_get("/products/search", {"q": " ".join(query.split()[:3]), "limit": 200})
    enriched = []
    budget = float(intent.get("maximumBudget", 0))
    for product in result.get("products", []):
        matched_category = not category or product.get("category") == category
        currency_matches = intent.get("currency") == "USD"
        total = float(product.get("price", 0)) * 1.05 + FEE_SHIPPING
        budget_matches = currency_matches and total <= budget
        matches = [
            {
                "name": requirement.get("name", "Specification"),
                "requested": requirement.get("value", ""),
                "status": "Not available for verification",
                "explanation": "The public product catalogue does not provide this technical specification.",
            }
            for requirement in intent.get("requirements", [])
        ]
        available_signals = 1 + int(currency_matches)
        percentage = round(
            (int(matched_category) + int(bool(budget_matches))) / max(available_signals, 1) * 100
        )
        recommendation_status = (
            "Budget Exceeded" if currency_matches and not budget_matches
            else "Currency Mismatch" if not currency_matches
            else "Matches Requirements" if matched_category and not matches
            else "Specification Mismatch" if matched_category and matches
            else "Category Mismatch"
        )
        enriched.append({
            "product": product,
            "analysis": {
                "percentage": percentage,
                "categoryMatched": matched_category,
                "budgetMatched": budget_matches if currency_matches else None,
                "matches": matches,
                "status": recommendation_status,
            },
        })
    add_audit(user["id"], "Product API data retrieved", f"Retrieved {len(enriched)} recommendation product(s).")
    return {"recommendations": enriched, "total": len(enriched)}


@app.get("/api/cart")
async def get_cart(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    items = await current_cart(user["id"])
    return {"items": items, "totals": cart_price(items)}


@app.post("/api/cart/items")
async def add_cart_item(
    payload: CartItemRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    await fetch_product(payload.product_id)
    with connect() as connection:
        connection.execute(
            """INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)
               ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + excluded.quantity""",
            (user["id"], payload.product_id, payload.quantity),
        )
    add_audit(user["id"], "Cart changed", f"Added product {payload.product_id} to the cart.")
    return await get_cart(user)


@app.put("/api/cart/items/{product_id}")
async def update_cart_item(
    product_id: int,
    payload: CartQuantityRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
            (payload.quantity, user["id"], product_id),
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item was not found.")
    add_audit(user["id"], "Cart changed", f"Updated product {product_id} quantity.")
    return await get_cart(user)


@app.delete("/api/cart/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(product_id: int, user: dict[str, Any] = Depends(get_current_user)) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user["id"], product_id),
        )
    add_audit(user["id"], "Cart changed", f"Removed product {product_id} from the cart.")


@app.delete("/api/cart/items", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(user: dict[str, Any] = Depends(get_current_user)) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM cart_items WHERE user_id = ?", (user["id"],))
    add_audit(user["id"], "Cart cleared", "Cleared cart after a completed purchase.")


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    items = await current_cart(user["id"])
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create an order from an empty cart.")
    totals = cart_price(items)
    now = utc_now()
    order_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            """INSERT INTO orders
               (id, user_id, version, intent_json, cart_json, total, currency, status, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?, ?, ?, 'pending_verification', ?, ?)""",
            (
                order_id, user["id"], json_dump(payload.intent), json_dump(items),
                totals["total"], totals["currency"], now, now,
            ),
        )
    add_audit(user["id"], "Order created", f"Created order {order_id} version 1.")
    return {
        "id": order_id,
        "version": 1,
        "status": "pending_verification",
        "items": items,
        "intent": payload.intent,
        "totals": totals,
        "created_at": now,
    }


@app.post("/api/verification/order")
async def verify_order(
    payload: VerifyOrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    items = await current_cart(user["id"])
    with connect() as connection:
        order = require_order(connection, payload.order_id, user["id"])
        if not order_matches_cart(order, items):
            checks = {
                "status": "Failed",
                "order_version": order["version"],
                "totals": cart_price(items),
                "checks": [{
                    "name": "Order version",
                    "status": "Failed",
                    "reason": "The backend cart changed after order creation. Create a new order and verify it again.",
                    "critical": True,
                }],
            }
        else:
            checks = build_verification(items, json.loads(order["intent_json"]), order["version"])
        state = "verified" if checks["status"] == "Passed" else "verification_failed"
        connection.execute(
            "UPDATE orders SET status = ?, checks_json = ?, updated_at = ? WHERE id = ?",
            (state, json_dump(checks), utc_now(), payload.order_id),
        )
    add_audit(user["id"], "IntentLock verification completed", f"Order {payload.order_id} verification result: {checks['status']}.")
    return {"order_id": payload.order_id, **checks}


@app.post("/api/approvals/{order_id}/approve")
async def approve_order(
    order_id: str,
    payload: ApprovalRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    items = await current_cart(user["id"])
    with connect() as connection:
        order = require_order(connection, order_id, user["id"])
        if order["version"] != payload.order_version or not order_matches_cart(order, items):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order changed after verification. Recreate and verify it before approval.")
        if order["status"] != "verified":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order must pass backend verification before approval.")
        connection.execute(
            "UPDATE orders SET status = 'approved', updated_at = ? WHERE id = ?",
            (utc_now(), order_id),
        )
    add_audit(user["id"], "Customer approval recorded", f"Customer approved order {order_id} version {payload.order_version}.")
    return {"order_id": order_id, "order_version": payload.order_version, "status": "approved"}


@app.post("/api/payments/create-order")
async def create_payment_order(
    payload: VerifyOrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    items = await current_cart(user["id"])
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = require_order(connection, payload.order_id, user["id"])
        if not order_matches_cart(order, items):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved order is stale; reverify and approve the current cart.")
        verification = json.loads(order["checks_json"] or "{}")
        if verification.get("status") != "Passed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Backend verification must pass before payment.")
        if order["status"] in {"paypal_pending", "reconciliation_required"} and order["paypal_order_id"]:
            existing_paypal_order_id = order["paypal_order_id"]
            existing_approval_url = order["paypal_approval_url"]
            create_request_id = order["paypal_create_request_id"]
        elif order["status"] in {"approved", "paypal_creating"} or (
            order["status"] == "reconciliation_required"
            and not order["paypal_order_id"]
            and order["paypal_create_request_id"]
        ):
            existing_paypal_order_id = None
            existing_approval_url = None
            create_request_id = order["paypal_create_request_id"] or payment_request_id(
                "create", order["id"]
            )
            connection.execute(
                """
                UPDATE orders
                SET status = 'paypal_creating', paypal_create_request_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (create_request_id, utc_now(), order["id"], user["id"]),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TrustPay order is not eligible for PayPal checkout.",
            )

    if existing_paypal_order_id and existing_approval_url:
        return {
            "order_id": order["id"],
            "paypal_order_id": existing_paypal_order_id,
            "approval_url": existing_approval_url,
            "status": "PENDING",
        }

    try:
        token = await paypal_access_token()
    except HTTPException:
        if not existing_paypal_order_id:
            with connect() as connection:
                connection.execute(
                    """
                    UPDATE orders
                    SET status = 'approved', updated_at = ?
                    WHERE id = ? AND user_id = ? AND status = 'paypal_creating'
                    """,
                    (utc_now(), order["id"], user["id"]),
                )
        raise

    if existing_paypal_order_id:
        try:
            response_status, paypal_order = await paypal_api_request(
                "GET",
                f"/v2/checkout/orders/{quote(existing_paypal_order_id, safe='')}",
                access_token=token,
            )
        except (PayPalTransportError, HTTPException) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="PayPal order status could not be confirmed. Retry checkout after reconciliation.",
            ) from error
        if response_status != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="PayPal order status could not be confirmed.",
            )
        if paypal_order.get("id") != existing_paypal_order_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal returned a different order than the one approved.",
            )
        if paypal_order.get("status") == "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal already reports a completed order. Return to the payment page to reconcile it.",
            )
        if paypal_order.get("status") != "CREATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal order is not awaiting buyer approval.",
            )
        validate_paypal_purchase_unit(paypal_order, order, existing_paypal_order_id)
        approval_url = paypal_approval_url(paypal_order)
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders
                SET status = 'paypal_pending', paypal_approval_url = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status IN ('paypal_pending', 'reconciliation_required')
                """,
                (approval_url, utc_now(), order["id"], user["id"]),
            )
        return {
            "order_id": order["id"],
            "paypal_order_id": existing_paypal_order_id,
            "approval_url": approval_url,
            "status": "PENDING",
        }

    amount = f"{Decimal(str(order['total'])).quantize(Decimal('0.01')):.2f}"
    return_url = f"{FRONTEND_BASE_URL}/payment?order_id={order['id']}"
    try:
        response_status, paypal_order = await paypal_api_request(
            "POST",
            "/v2/checkout/orders",
            payload={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "reference_id": order["id"],
                    "amount": {"currency_code": order["currency"], "value": amount},
                }],
                "application_context": {
                    "brand_name": "TrustPay AI Sandbox Demo",
                    "user_action": "PAY_NOW",
                    "return_url": return_url,
                    "cancel_url": f"{FRONTEND_BASE_URL}/payment?cancelled=1&order_id={order['id']}",
                },
            },
            request_id=create_request_id,
            access_token=token,
        )
    except HTTPException:
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders
                SET status = 'reconciliation_required', updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'paypal_creating'
                """,
                (utc_now(), order["id"], user["id"]),
            )
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal order creation response could not be validated for order {order['id']}.",
        )
        raise
    except PayPalTransportError as error:
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders
                SET status = 'reconciliation_required', updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'paypal_creating'
                """,
                (utc_now(), order["id"], user["id"]),
            )
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal order creation could not be confirmed for order {order['id']}.",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal order creation could not be confirmed. Retry with the same TrustPay order.",
        ) from error

    if not 200 <= response_status < 300:
        next_status = "reconciliation_required" if response_status >= 500 else "approved"
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders SET status = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'paypal_creating'
                """,
                (next_status, utc_now(), order["id"], user["id"]),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal Sandbox could not create the checkout order.",
        )

    paypal_order_id = paypal_order.get("id")
    if not isinstance(paypal_order_id, str) or not paypal_order_id or len(paypal_order_id) > 128:
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders SET status = 'reconciliation_required', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (utc_now(), order["id"], user["id"]),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal returned an invalid order identifier; reconciliation is required.",
        )

    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest_order = require_order(connection, order["id"], user["id"])
        connection.execute(
            """
            UPDATE orders
            SET paypal_order_id = ?, status = 'paypal_pending', updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (paypal_order_id, utc_now(), order["id"], user["id"]),
        )
    try:
        if paypal_create_response_needs_refresh(paypal_order):
            try:
                refreshed_status, refreshed_order = await paypal_api_request(
                    "GET",
                    f"/v2/checkout/orders/{quote(paypal_order_id, safe='')}",
                    access_token=token,
                )
            except (PayPalTransportError, HTTPException) as error:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal order details could not be confirmed.",
                ) from error
            if refreshed_status != status.HTTP_200_OK:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="PayPal order details could not be confirmed.",
                )
            paypal_order = refreshed_order

        if paypal_order.get("id") != paypal_order_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal returned a different order than the one approved.",
            )
        if paypal_order.get("status") != "CREATED":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="PayPal returned an unexpected order status.",
            )
        validate_paypal_purchase_unit(paypal_order, order, paypal_order_id)
        approval_url = paypal_approval_url(paypal_order)
    except HTTPException:
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders SET status = 'reconciliation_required', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (utc_now(), order["id"], user["id"]),
            )
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal order response did not match TrustPay order {order['id']}.",
        )
        raise

    latest_items = await current_cart(user["id"])
    if not order_matches_cart(latest_order, latest_items):
        with connect() as connection:
            connection.execute(
                """
                UPDATE orders
                SET status = 'reconciliation_required', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (utc_now(), order["id"], user["id"]),
            )
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"Cart changed while creating PayPal order for TrustPay order {order['id']}.",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cart changed while creating checkout. Cancel the PayPal order and reverify the cart.",
        )

    with connect() as connection:
        connection.execute(
            """
            UPDATE orders
            SET paypal_approval_url = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND status = 'paypal_pending'
            """,
            (approval_url, utc_now(), order["id"], user["id"]),
        )
    add_audit(
        user["id"],
        "Sandbox payment initiated",
        f"Created PayPal Sandbox order for TrustPay order {order['id']}.",
    )
    return {
        "order_id": order["id"],
        "paypal_order_id": paypal_order_id,
        "approval_url": approval_url,
        "status": "PENDING",
    }


@app.post("/api/payments/capture-order")
async def capture_payment(
    payload: PayPalCaptureRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute(
            "SELECT * FROM orders WHERE paypal_order_id = ? AND user_id = ?",
            (payload.paypal_order_id, user["id"]),
        ).fetchone()
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PayPal order was not found for this account.",
            )
        if order["status"] == "completed":
            existing = connection.execute(
                "SELECT * FROM transactions WHERE order_id = ? AND user_id = ?",
                (order["id"], user["id"]),
            ).fetchone()
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Completed payment is missing its transaction record. Reconciliation is required.",
                )
            add_audit(
                user["id"],
                "Duplicate capture prevented",
                f"Repeated capture request returned the existing transaction for order {order['id']}.",
                connection,
            )
            return {
                "id": existing["id"],
                "order_id": existing["order_id"],
                "paypal_reference": existing["paypal_reference"],
                "amount": existing["amount"],
                "currency": existing["currency"],
                "date": existing["date"],
                "status": "COMPLETED",
                "method": existing["method"],
                "product": existing["product"],
                "cart_cleared": False,
            }
        if order["status"] == "cancelled":
            response = payment_pending_response(order)
            response["status"] = "CANCELLED"
            return response
        if order["status"] not in {
            "paypal_pending",
            "paypal_capturing",
            "reconciliation_required",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PayPal order is not eligible for capture.",
            )
        verification = json.loads(order["checks_json"] or "{}")
        if verification.get("status") != "Passed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Backend verification must pass before payment capture.",
            )
        previous_status = order["status"]
        capture_request_id = order["paypal_capture_request_id"] or payment_request_id(
            "capture", order["id"]
        )
        connection.execute(
            """
            UPDATE orders
            SET status = 'paypal_capturing', paypal_capture_request_id = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (capture_request_id, utc_now(), order["id"], user["id"]),
        )

    try:
        token = await paypal_access_token()
    except HTTPException:
        set_payment_status(order["id"], user["id"], previous_status)
        raise

    add_audit(
        user["id"],
        "Payment capture requested",
        f"Requested PayPal capture for TrustPay order {order['id']}.",
    )
    try:
        paypal_status, paypal_order = await paypal_api_request(
            "GET",
            f"/v2/checkout/orders/{quote(payload.paypal_order_id, safe='')}",
            access_token=token,
        )
    except HTTPException:
        set_payment_status(order["id"], user["id"], previous_status)
        raise
    except PayPalTransportError:
        set_payment_status(order["id"], user["id"], "reconciliation_required")
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal status could not be checked before capture for order {order['id']}.",
        )
        return payment_pending_response(order)

    if paypal_status != status.HTTP_200_OK:
        set_payment_status(order["id"], user["id"], "reconciliation_required")
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal status could not be checked before capture for order {order['id']}.",
        )
        return payment_pending_response(order)

    provider_status = paypal_order.get("status")
    if provider_status == "COMPLETED":
        try:
            capture_id, amount, currency = validate_paypal_capture(
                paypal_order,
                order,
                payload.paypal_order_id,
            )
        except HTTPException:
            set_payment_status(order["id"], user["id"], "reconciliation_required")
            add_audit(
                user["id"],
                "Payment reconciliation required",
                f"PayPal payment did not match TrustPay order {order['id']}.",
            )
            raise
        return record_completed_payment(
            order,
            user["id"],
            payload.paypal_order_id,
            capture_id,
            amount,
            currency,
        )

    if provider_status in {"VOIDED", "CANCELLED"}:
        set_payment_status(order["id"], user["id"], "cancelled")
        add_audit(
            user["id"],
            "Sandbox payment cancelled",
            f"PayPal reported a cancelled order for TrustPay order {order['id']}.",
        )
        response = payment_pending_response(order)
        response["status"] = "CANCELLED"
        return response

    if provider_status != "APPROVED":
        set_payment_status(
            order["id"],
            user["id"],
            "paypal_pending" if provider_status == "CREATED" else "reconciliation_required",
        )
        return payment_pending_response(order)

    try:
        validate_paypal_purchase_unit(paypal_order, order)
    except HTTPException:
        set_payment_status(order["id"], user["id"], "reconciliation_required")
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal order details did not match TrustPay order {order['id']}.",
        )
        raise

    try:
        capture_status, capture_response = await paypal_api_request(
            "POST",
            f"/v2/checkout/orders/{quote(payload.paypal_order_id, safe='')}/capture",
            payload={},
            request_id=capture_request_id,
            access_token=token,
        )
    except (HTTPException, PayPalTransportError):
        return await reconcile_paypal_order(
            order,
            user["id"],
            payload.paypal_order_id,
            token,
        )

    if not 200 <= capture_status < 300 or capture_response.get("status") != "COMPLETED":
        return await reconcile_paypal_order(
            order,
            user["id"],
            payload.paypal_order_id,
            token,
        )

    try:
        capture_id, amount, currency = validate_paypal_capture(
            capture_response,
            order,
            payload.paypal_order_id,
        )
    except HTTPException:
        set_payment_status(order["id"], user["id"], "reconciliation_required")
        add_audit(
            user["id"],
            "Payment reconciliation required",
            f"PayPal capture details did not match TrustPay order {order['id']}.",
        )
        raise
    return record_completed_payment(
        order,
        user["id"],
        payload.paypal_order_id,
        capture_id,
        amount,
        currency,
    )


@app.post("/api/payments/cancel-order")
async def cancel_payment_order(
    payload: VerifyOrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = require_order(connection, payload.order_id, user["id"])
        if order["status"] == "completed":
            existing = connection.execute(
                "SELECT * FROM transactions WHERE order_id = ? AND user_id = ?",
                (order["id"], user["id"]),
            ).fetchone()
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Completed payment is missing its transaction record. Reconciliation is required.",
                )
            return {
                "id": existing["id"],
                "order_id": existing["order_id"],
                "paypal_reference": existing["paypal_reference"],
                "amount": existing["amount"],
                "currency": existing["currency"],
                "date": existing["date"],
                "status": "COMPLETED",
                "method": existing["method"],
                "product": existing["product"],
                "cart_cleared": False,
            }
        if order["status"] == "cancelled":
            response = payment_pending_response(order)
            response["status"] = "CANCELLED"
            return response
        if order["status"] == "approved" and not order["paypal_order_id"]:
            connection.execute(
                """
                UPDATE orders SET status = 'cancelled', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (utc_now(), order["id"], user["id"]),
            )
            paypal_order_id = None
        elif order["status"] in {"paypal_pending", "reconciliation_required"}:
            if not order["paypal_order_id"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="PayPal order cannot be cancelled until its status is reconciled.",
                )
            paypal_order_id = order["paypal_order_id"]
            connection.execute(
                """
                UPDATE orders SET status = 'paypal_reconciling', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (utc_now(), order["id"], user["id"]),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TrustPay order is not eligible for cancellation.",
            )

    if paypal_order_id is None:
        add_audit(
            user["id"],
            "Sandbox payment cancelled",
            f"Customer cancelled TrustPay order {order['id']} before PayPal checkout.",
        )
        response = payment_pending_response(order)
        response["status"] = "CANCELLED"
        return response

    try:
        token = await paypal_access_token()
    except HTTPException:
        set_payment_status(order["id"], user["id"], "reconciliation_required")
        raise

    return await reconcile_paypal_order(
        order,
        user["id"],
        paypal_order_id,
        token,
        cancel_if_unpaid=True,
    )


@app.get("/api/transactions")
def list_transactions(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC, rowid DESC",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/dashboard")
def dashboard(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with connect() as connection:
        requests_total = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE user_id = ? AND type = 'Purchase policy created'",
            (user["id"],),
        ).fetchone()[0]
        verified_orders = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status IN ('verified', 'approved', 'paypal_pending', 'completed')",
            (user["id"],),
        ).fetchone()[0]
        blocked_orders = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'verification_failed'",
            (user["id"],),
        ).fetchone()[0]
        transactions = connection.execute(
            "SELECT id, order_id, product, amount, currency, date, method, status, verification FROM transactions WHERE user_id = ? ORDER BY date DESC, rowid DESC LIMIT 5",
            (user["id"],),
        ).fetchall()
        activity = connection.execute(
            "SELECT type, timestamp, description FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 5",
            (user["id"],),
        ).fetchall()
    return {
        "total_requests": requests_total,
        "verified_orders": verified_orders,
        "blocked_transactions": blocked_orders,
        "recent_transactions": [dict(row) for row in transactions],
        "security_activity": [dict(row) for row in activity],
    }


@app.get("/api/audit")
def list_audit(user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT id, type, timestamp, description, previous_hash AS previousHash, hash,
                      'Pending' AS integrity
               FROM audit_events WHERE user_id = ? ORDER BY rowid""",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/audit/verify-integrity")
def verify_audit(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT id, type, timestamp, description, previous_hash, hash
               FROM audit_events WHERE user_id = ? ORDER BY rowid""",
            (user["id"],),
        ).fetchall()
    previous_hash = "GENESIS"
    for row in rows:
        payload = {
            "id": row["id"],
            "type": row["type"],
            "timestamp": row["timestamp"],
            "description": row["description"],
        }
        expected = hashlib.sha256(f"{previous_hash}:{json_dump(payload)}".encode()).hexdigest()
        if row["previous_hash"] != previous_hash or not hmac.compare_digest(row["hash"], expected):
            return {"valid": False, "records_checked": len(rows)}
        previous_hash = row["hash"]
    return {"valid": True, "records_checked": len(rows)}
