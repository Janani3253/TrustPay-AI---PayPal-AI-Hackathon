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
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.core.config import settings
from app.core.database import check_db_connectivity, close_db_engine
from app.core.dependencies import get_current_user, get_optional_current_user
from app.routers import (
    auth_router,
    users_router,
    products_router,
    platforms_router,
    intent_router,
    security_router,
    cart_router,
    verification_router,
    orders_router,
    approvals_router,
    payments_router,
    transactions_router,
    dashboard_router,
    audit_router,
)
from app.services.product_service import product_service
from app.services.intent_service import intent_service
from app.core.audit import add_audit
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

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(products_router)
app.include_router(platforms_router)
app.include_router(intent_router)
app.include_router(security_router)
app.include_router(cart_router)
app.include_router(verification_router)
app.include_router(orders_router)
app.include_router(approvals_router)
app.include_router(payments_router)
app.include_router(transactions_router)
app.include_router(dashboard_router)
app.include_router(audit_router)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_db_engine()
    await product_service.close()
    await intent_service.close()


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


# get_current_user provided by app.core.dependencies
# add_audit is imported from app.core.audit
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
    try:
        product = await product_service.get_product_details(product_id)
        return product.model_dump(by_alias=True)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Product catalogue returned an invalid product.",
        ) from error


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
        r"(?:under|below|less than|maximum|max|budget(?: of)?|up to)\s*(?:Γé╣|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?",
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
    elif re.search(r"Γé╣|inr|rupees?", text, re.IGNORECASE):
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
    if not client_id or not client_secret:
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
            response.raise_for_status()
            return response.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not authenticate with PayPal Sandbox.") from error


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "application": settings.APP_NAME,
        "environment": settings.APP_ENV,
    }


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    db_status = await check_db_connectivity()
    if db_status.get("status") == "connected":
        return {
            "status": "ok",
            "application": settings.APP_NAME,
            "services": {
                "postgresql": {
                    "status": "connected",
                    "engine": "PostgreSQL",
                    "version": db_status.get("version", "16"),
                }
            },
        }
    elif db_status.get("status") == "not_configured":
        return {
            "status": "degraded",
            "application": settings.APP_NAME,
            "services": {
                "postgresql": {
                    "status": "not_configured",
                }
            },
        }
    else:
        return {
            "status": "degraded",
            "application": settings.APP_NAME,
            "services": {
                "postgresql": {
                    "status": "unavailable",
                }
            },
        }


# /api/intent/parse moved to app.routers.intent_router


@app.get("/api/recommendations/search")
async def recommendations_get(
    request: str = "",
    category: str = "",
    maximumBudget: float = 1000.0,
    currency: str = "USD",
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    payload = {
        "intent": {
            "request": request,
            "category": category,
            "maximumBudget": maximumBudget,
            "currency": currency,
            "requirements": [],
        }
    }
    return await recommendations(payload=payload, user=user)


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
    try:
        if category:
            if not isinstance(category, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", category):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid product category.")
            result = await product_service.list_products(category=category, limit=200)
        else:
            search_query = " ".join(query.split()[:3]).strip()
            if search_query:
                result = await product_service.search_products(query=search_query, limit=200)
            else:
                result = await product_service.list_products(limit=200)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue service is currently unavailable.",
        ) from err
    enriched = []
    budget = float(intent.get("maximumBudget", 0))
    for norm_prod in result.products:
        product = norm_prod.model_dump(by_alias=True)
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


# Legacy cart routes moved to cart_router
@app.get("/api/legacy-cart")
async def get_cart(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    items = await current_cart(user["id"])
    return {"items": items, "totals": cart_price(items)}


@app.post("/api/legacy-cart/items")
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


@app.put("/api/legacy-cart/items/{product_id}")
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


@app.delete("/api/legacy-cart/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(product_id: int, user: dict[str, Any] = Depends(get_current_user)) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user["id"], product_id),
        )
    add_audit(user["id"], "Cart changed", f"Removed product {product_id} from the cart.")


@app.delete("/api/legacy-cart/items", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(user: dict[str, Any] = Depends(get_current_user)) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM cart_items WHERE user_id = ?", (user["id"],))
    add_audit(user["id"], "Cart cleared", "Cleared cart after a completed purchase.")


@app.post("/api/legacy-orders", status_code=status.HTTP_201_CREATED)
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


# /api/verification/order moved to verification_router
@app.post("/api/legacy-verification/order")
async def verify_order(
    payload: VerifyOrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        order = require_order(connection, payload.order_id, user["id"])
        items = await current_cart(user["id"])
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


@app.post("/api/legacy-approvals/{order_id}/approve")
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


@app.post("/api/legacy-payments/create-order")
async def create_payment_order(
    payload: VerifyOrderRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    items = await current_cart(user["id"])
    with connect() as connection:
        order = require_order(connection, payload.order_id, user["id"])
        if order["status"] != "approved" or not order_matches_cart(order, items):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved order is stale; reverify and approve the current cart.")
        verification = json.loads(order["checks_json"] or "{}")
        if verification.get("status") != "Passed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Backend verification must pass before payment.")
    token = await paypal_access_token()
    amount = f"{float(order['total']):.2f}"
    return_url = f"{FRONTEND_BASE_URL}/payment?order_id={order['id']}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{PAYPAL_API_BASE_URL}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
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
            )
            response.raise_for_status()
            paypal_order = response.json()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="PayPal Sandbox could not create the checkout order.") from error
    approval_url = next((link["href"] for link in paypal_order.get("links", []) if link.get("rel") == "approve"), None)
    if not approval_url:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="PayPal Sandbox did not return an approval URL.")
    with connect() as connection:
        connection.execute(
            "UPDATE orders SET paypal_order_id = ?, status = 'paypal_pending', updated_at = ? WHERE id = ?",
            (paypal_order["id"], utc_now(), order["id"]),
        )
    add_audit(user["id"], "Sandbox payment initiated", f"Created PayPal Sandbox order for TrustPay order {order['id']}.")
    return {"order_id": order["id"], "paypal_order_id": paypal_order["id"], "approval_url": approval_url, "status": "PENDING"}


@app.post("/api/legacy-payments/capture-order")
async def capture_payment(
    payload: PayPalCaptureRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        order = connection.execute(
            "SELECT * FROM orders WHERE paypal_order_id = ? AND user_id = ?",
            (payload.paypal_order_id, user["id"]),
        ).fetchone()
    if order is None or order["status"] != "paypal_pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PayPal order is not pending for this account.")
    items = await current_cart(user["id"])
    if not order_matches_cart(order, items):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cart changed before payment capture.")
    token = await paypal_access_token()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{PAYPAL_API_BASE_URL}/v2/checkout/orders/{payload.paypal_order_id}/capture",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={},
            )
            response.raise_for_status()
            capture = response.json()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="PayPal Sandbox capture could not be completed.") from error
    status_text = capture.get("status", "PENDING")
    capture_entries = [
        entry
        for unit in capture.get("purchase_units", [])
        for entry in unit.get("payments", {}).get("captures", [])
    ]
    paypal_reference = capture_entries[0].get("id") if capture_entries else payload.paypal_order_id
    transaction_id = f"TRX-{uuid.uuid4().hex[:12].upper()}"
    transaction_date = datetime.now(timezone.utc).date().isoformat()
    if status_text == "COMPLETED":
        with connect() as connection:
            connection.execute(
                """INSERT INTO transactions
                   (id, user_id, order_id, product, amount, currency, date, method, status, verification, paypal_reference)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    transaction_id, user["id"], order["id"],
                    ", ".join(item["product"].get("title", "Product") for item in items),
                    order["total"], order["currency"], transaction_date, "PayPal Sandbox",
                    "Completed", "Backend verified", paypal_reference,
                ),
            )
            connection.execute(
                "UPDATE orders SET status = 'completed', updated_at = ? WHERE id = ?",
                (utc_now(), order["id"]),
            )
        add_audit(user["id"], "Sandbox payment completed", f"PayPal Sandbox capture status: COMPLETED for order {order['id']}.")
    else:
        with connect() as connection:
            connection.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (f"paypal_{status_text.lower()}", utc_now(), order["id"]),
            )
        add_audit(user["id"], "Sandbox payment pending", f"PayPal Sandbox returned status {status_text} for order {order['id']}.")
    return {
        "id": transaction_id if status_text == "COMPLETED" else None,
        "order_id": order["id"],
        "paypal_reference": paypal_reference,
        "amount": order["total"],
        "currency": order["currency"],
        "date": transaction_date,
        "status": status_text,
        "method": "PayPal Sandbox",
    }


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
