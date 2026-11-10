import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger(__name__)

from .database import connect, initialize_database
from .gemini import interpret_product_request
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
FX_API_BASE_URL = "https://api.frankfurter.dev/v2/rate"

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


def json_load(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


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


async def _fetch_catalogue_products(
    search_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    if search_terms:
        searched_products: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        searched_terms: set[str] = set()
        for term in search_terms:
            query = re.sub(r"\s+", " ", str(term)).strip()[:120]
            normalized_query = query.casefold()
            if not query or normalized_query in searched_terms:
                continue
            searched_terms.add(normalized_query)
            if len(searched_terms) > 3:
                break
            try:
                result = await dummyjson_get(
                    "/products/search",
                    {"q": query, "limit": 100},
                )
            except HTTPException as error:
                if error.status_code != status.HTTP_502_BAD_GATEWAY:
                    raise
                logger.warning(
                    "Product provider search failed; falling back to catalogue listing."
                )
                break
            if not isinstance(result, dict) or not isinstance(result.get("products"), list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The product catalogue returned an invalid search result.",
                )
            if any(not isinstance(product, dict) for product in result["products"]):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The product catalogue returned an invalid product record.",
                )
            for product in result["products"]:
                product_id = product.get("id")
                if product_id is not None and product_id in seen_ids:
                    continue
                if product_id is not None:
                    seen_ids.add(product_id)
                searched_products.append(product)
        if searched_products:
            return searched_products

    page_size = 100
    result = await dummyjson_get("/products", {"limit": page_size, "skip": 0})
    if not isinstance(result, dict) or not isinstance(result.get("products"), list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue returned an invalid product list.",
        )
    if any(not isinstance(product, dict) for product in result["products"]):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue returned an invalid product record.",
        )

    products = list(result["products"])
    total = result.get("total")
    if total is None:
        return products
    if isinstance(total, bool) or not isinstance(total, int) or total < len(products):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue returned invalid pagination metadata.",
        )

    while len(products) < total:
        page = await dummyjson_get(
            "/products",
            {"limit": page_size, "skip": len(products)},
        )
        if not isinstance(page, dict) or not isinstance(page.get("products"), list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The product catalogue returned an invalid product page.",
            )
        page_products = page["products"]
        if not page_products or any(not isinstance(product, dict) for product in page_products):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The product catalogue returned an incomplete product page.",
            )
        page_total = page.get("total", total)
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < len(products) + len(page_products)
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The product catalogue returned invalid pagination metadata.",
            )
        total = page_total
        products.extend(page_products)

    unique_products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = product.get("id")
        if product_id is not None:
            key = str(product_id)
            if key in seen_ids:
                continue
            seen_ids.add(key)
        unique_products.append(product)
    return unique_products


async def get_exchange_rate(base: str, quote: str) -> dict[str, Any] | None:
    today = datetime.now(timezone.utc).date()

    if base not in {"USD", "INR"} or quote not in {"USD", "INR"}:
        return None

    if base == quote:
        return {"rate": 1.0, "date": today.isoformat()}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{FX_API_BASE_URL}/{base}/{quote}",
                params={"date": today.isoformat()},
            )
            response.raise_for_status()
            data = response.json()

        rate = Decimal(str(data["rate"]))
        rate_date = datetime.strptime(data["date"], "%Y-%m-%d").date()

        age_days = (today - rate_date).days

        if (
            not rate.is_finite()
            or rate <= 0
            or age_days < 0
            or age_days > 7
        ):
            return None

        return {"rate": float(rate), "date": rate_date.isoformat()}

    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation):
        return None


def convert_currency_amount(
    amount: float | Decimal,
    base: str,
    quote: str,
    exchange_rate_info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if base not in {"USD", "INR"} or quote not in {"USD", "INR"}:
        return None

    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0:
            return None

        if base == quote:
            rate = Decimal("1")
            rate_date = (
                str(exchange_rate_info["date"])
                if exchange_rate_info and exchange_rate_info.get("date")
                else datetime.now(timezone.utc).date().isoformat()
            )
        else:
            if not exchange_rate_info:
                return None
            rate = Decimal(str(exchange_rate_info["rate"]))
            rate_date = str(exchange_rate_info["date"])
            if not rate.is_finite() or rate <= 0 or not rate_date:
                return None

        datetime.strptime(rate_date, "%Y-%m-%d")
        converted = (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        converted_float = float(converted)
        if not Decimal(str(converted_float)).is_finite():
            return None
        return {
            "amount": converted_float,
            "rate": float(rate),
            "date": rate_date,
        }
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None


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


_REQUEST_STOP_WORDS = {
    "a", "an", "the", "and", "or", "with", "for", "of", "in", "on", "to",
    "my", "me", "please", "want", "need", "buy", "find", "looking", "search",
    "under", "below", "less", "than", "maximum", "max", "minimum", "min",
    "budget", "up", "at", "least", "more", "between", "from", "to", "price",
    "do", "not", "dont", "no", "add", "without", "exclude", "excluding",
    "prefer", "preferably", "ideally", "optional", "would", "like", "only",
    "must", "require", "required", "has", "have", "that", "is", "are", "be",
    "it", "its", "by", "brand", "manufacturer", "size", "sized",
    "quantity", "qty", "units", "unit", "pieces", "piece", "pairs", "pair",
    "trusted", "seller", "sellers", "accessory", "accessories",
    "usd", "inr", "rupee", "rupees", "dollar", "dollars", "rs",
    "good", "great", "best", "quality", "suitable", "recommend", "suggest",
}
_KNOWN_BRANDS = (
    "samsung", "apple", "dell", "hp", "lenovo", "xiaomi", "redmi",
    "oneplus", "oppo", "vivo", "sony", "asus", "acer", "motorola",
    "google", "realme", "nokia", "nike", "adidas", "lg", "microsoft",
    "bose", "boat", "philips", "panasonic", "whirlpool", "haier",
)
_BRAND_ALIASES = {
    "iphone": "apple",
    "ipad": "apple",
    "macbook": "apple",
    "galaxy": "samsung",
    "thinkpad": "lenovo",
    "pixel": "google",
}
_CATEGORY_PATTERNS = (
    (r"\b(laptops?|notebooks?|computers?)\b", "laptops", "laptop"),
    (r"\b(?:android\s+)?(?:phones?|mobiles?|smartphones?|iphones?)\b", "smartphones", "phone"),
    (r"\btablets?\b", "tablets", "tablet"),
    (r"\b(tvs?|televisions?)\b", "televisions", "television"),
    (r"\b(headphones?|earphones?|headsets?)\b", "headphones", "headphone"),
    (r"\bwatches?\b", "watches", "watch"),
    (r"\b(shoes?|sneakers?|trainers?)\b", "shoes", "shoe"),
    (r"\bfootwear\b", "shoes", "footwear"),
    (r"\b(pens?|stationery)\b", "stationery", "pen"),
    (r"\bbooks?\b", "books", "book"),
    (r"\b(bags?|backpacks?)\b", "bags", "bag"),
    (r"\b(clothes|clothing|apparel|garments?)\b", "clothing", "clothing"),
    (r"\b(sports?|athletic)\b", "sports", "sports"),
    (r"\bshirts?\b", "mens-shirts", "shirt"),
    (r"\bdresses?\b", "womens-dresses", "dress"),
    (r"\btables?\b", "furniture", "table"),
    (r"\bchairs?\b", "furniture", "chair"),
    (r"\bfurniture\b", "furniture", "furniture"),
    (r"\b(?:home )?appliances?\b", "appliances", "appliance"),
    (r"\b(?:refrigerators?|fridges?)\b", "appliances", "refrigerator"),
    (r"\bwashing machines?\b", "appliances", "washing machine"),
    (r"\b(?:microwaves?|air conditioners?|fans?)\b", "appliances", "appliance"),
)
_CATEGORY_ALIASES = {
    "smartphones": {"phone", "mobile", "smartphone", "android", "iphone"},
    "laptops": {"laptop", "notebook", "computer"},
    "tablets": {"tablet"},
    "televisions": {"tv", "television"},
    "headphones": {"headphone", "earphone", "headset"},
    "audio": {"audio"},
    "shoes": {"shoe", "sneaker", "trainer", "footwear"},
    "watches": {"watch", "smartwatch"},
    "shirts": {"shirt", "tshirt"},
    "dresses": {"dress"},
    "tables": {"table"},
    "chairs": {"chair"},
    "furniture": {"furniture"},
    "appliances": {"appliance"},
    "refrigerators": {"refrigerator", "fridge"},
    "washing-machines": {"washer", "washing machine"},
    "stationery": {"pen", "pencil", "stationery", "writing instrument"},
    "books": {"book"},
    "bags": {"bag", "backpack", "handbag"},
    "clothing": {"clothing", "clothes", "apparel", "garment"},
    "sports": {"sport", "sports", "athletic"},
}
_SPECIFICATION_PATTERNS = (
    (r"(?P<value>\d+(?:\.\d+)?\s?(?:gb|tb))\s?ram\b", "RAM"),
    (r"(?P<value>\d+(?:\.\d+)?\s?(?:gb|tb))\s?(?:ssd|hdd|storage)\b", "Storage"),
    (r"\b(?P<value>(?:intel\s*)?i[3579]|ryzen\s*[3579])\b", "Processor"),
    (r"\b(?P<value>5g)\b", "Network"),
    (r"\b(?:size|sized)\s+(?:of\s+)?(?P<value>[a-z0-9]+)\b", "Size"),
)


def _normalized_tokens(value: Any) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", str(value).lower()):
        if len(token) > 1 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith(("ches", "shes", "xes", "zes", "sses")):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def _extract_requirements(text: str) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pattern, label in _SPECIFICATION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group("value")
            key = (label.casefold(), re.sub(r"[^a-z0-9]", "", value.casefold()))
            if key not in seen:
                requirements.append({"name": label, "value": value})
                seen.add(key)

    broad_units = (
        r"gb|tb|mb|litres?|liters?|l|ml|cm|mm|metres?|meters?|m|"
        r"inches?|inch|in|kg|g|mah|w|watts?|hz|mp|megapixels?"
    )
    for match in re.finditer(
        rf"\b(?P<operator>at least|minimum(?: of)?|no less than)?\s*"
        rf"(?P<value>\d+(?:\.\d+)?\s*(?:{broad_units}))\s*"
        rf"(?P<name>capacity|storage|memory|ram|screen|display|size|weight|"
        rf"dimensions?|width|height|depth|resolution|power|battery)?\b",
        text,
        re.IGNORECASE,
    ):
        value = match.group("value").strip()
        name = (match.group("name") or "Specification").title()
        operator = "minimum" if match.group("operator") else "exact"
        key = (name.casefold(), re.sub(r"[^a-z0-9]", "", value.casefold()))
        if key not in seen and not any(
            old_name == name.casefold() and old_value.startswith(key[1])
            for old_name, old_value in seen
        ):
            requirements.append({"name": name, "value": value, "operator": operator})
            seen.add(key)

    for pattern, name in [
        (r"\b(black|white|red|blue|green|yellow|pink|purple|grey|gray|brown)\b", "Color"),
        (r"\b(cotton|wooden|wood|leather|stainless steel|plastic|metal)\b", "Material"),
        (r"\b(wireless|bluetooth|waterproof|water-resistant|noise cancellation|"
         r"noise-cancelling|4k|8k|oled|led|touchscreen|gaming)\b", "Feature"),
    ]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1)
            key = (name.casefold(), re.sub(r"[^a-z0-9]", "", value.casefold()))
            if key not in seen:
                requirements.append({"name": name, "value": value})
                seen.add(key)
    return requirements


def _extract_exclusions(text: str) -> list[dict[str, str]]:
    exclusions: list[dict[str, str]] = []
    for match in re.finditer(
        r"\b(?:without|excluding|exclude|no(?!\s+(?:less|more)\s+than))\s+"
        r"(?P<value>[a-z][a-z -]*?)(?=\s+(?:under|below|less than|for|with|in|size)\b|[,.;]|$)",
        text,
        re.IGNORECASE,
    ):
        value = match.group("value").strip()
        if not value or value.casefold() in {"accessories", "accessory"}:
            continue
        name = "Material" if value.casefold() in {
            "leather", "wood", "wooden", "cotton", "plastic", "metal", "stainless steel",
        } else "Feature"
        exclusions.append({"name": name, "value": value})
    return exclusions


def _extract_brands(text: str, catalogue_brands: set[str] | None = None) -> list[str]:
    lowered = text.lower()
    candidates = set(_KNOWN_BRANDS)
    candidates.update(brand.lower() for brand in (catalogue_brands or set()) if brand.strip())
    requested = [
        brand for brand in candidates
        if re.search(r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])", lowered)
    ]
    explicit_brand = re.search(
        r"\b(?:brand(?:ed)?|manufacturer|by|from)\s+"
        r"(?P<brand>[a-z][a-z0-9&.-]*)",
        lowered,
    )
    if explicit_brand and explicit_brand.group("brand") not in _REQUEST_STOP_WORDS:
        requested.append(explicit_brand.group("brand"))
    for alias, brand in _BRAND_ALIASES.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", lowered):
            requested.append(brand)
    return sorted(set(requested))


def _product_brand_matches(
    requested_brands: list[str],
    product: dict[str, Any],
) -> bool | None:
    if not requested_brands:
        return None
    catalogue_brand = str(product.get("brand") or "").strip()
    brand_evidence = catalogue_brand or str(product.get("title") or "")
    available_brand_tokens = _normalized_tokens(brand_evidence)
    return all(
        _normalized_tokens(brand_name).issubset(available_brand_tokens)
        for brand_name in requested_brands
    )


def _product_category_evidence(product: dict[str, Any]) -> str:
    evidence = [str(product.get("title") or "")]
    tags = product.get("tags", [])
    if isinstance(tags, list):
        evidence.extend(str(tag) for tag in tags)
    return " ".join(evidence)


def _mandatory_query_text(text: str) -> str:
    return re.split(
        r",\s*prefer\b|\b(?:preferably|ideally|optional)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]


def _category_families(value: str) -> set[str]:
    tokens = _normalized_tokens(value)
    families = {
        family
        for family, aliases in _CATEGORY_ALIASES.items()
        if any(_normalized_tokens(alias).issubset(tokens) for alias in aliases)
    }
    if "accessory" in tokens:
        families.discard("smartphones")
    return families


def _category_vocabulary(category: str, category_terms: list[str]) -> set[str]:
    values = [category, *category_terms]
    families = set().union(*(_category_families(value) for value in values))
    vocabulary = set().union(*(_normalized_tokens(value) for value in values))
    for family in families:
        vocabulary.update(
            token
            for alias in _CATEGORY_ALIASES[family]
            for token in _normalized_tokens(alias)
            if token not in {"android", "iphone"}
        )
    return vocabulary


def _mandatory_request_terms(
    text: str,
    requirements: list[dict[str, Any]],
    category: str = "",
    category_terms: list[str] | None = None,
) -> set[str]:
    required_text = _mandatory_query_text(text)
    required_text = re.sub(
        r"\b(?:without|excluding|exclude|no(?!\s+(?:less|more)\s+than))\s+[^,.]+",
        " ",
        required_text,
        flags=re.IGNORECASE,
    )
    required_text = re.sub(
        r"\b(?:buy|get|need|want|find|quantity(?: of)?|qty)\s+\d+\s*"
        r"(?:units?|items?|pieces?|pairs?)?\b",
        " ",
        required_text,
        flags=re.IGNORECASE,
    )
    required_text = re.sub(
        r"\b(?:between|from)\s*(?:[^\w\s]\s*|rs\.?\s*|inr\s*|usd\s*)?"
        r"\d[\d,]*(?:\.\d+)?\s*(?:and|to|-)\s*"
        r"(?:[^\w\s]\s*|rs\.?\s*|inr\s*|usd\s*)?\d[\d,]*(?:\.\d+)?",
        " ",
        required_text,
        flags=re.IGNORECASE,
    )
    for requirement in requirements:
        value = str(requirement.get("value", "")).strip()
        if not value:
            continue
        required_text = re.sub(
            r"(?<![a-z0-9])" + re.escape(value) + r"(?![a-z0-9])",
            " ",
            required_text,
            flags=re.IGNORECASE,
        )
    required_text = re.sub(
        r"(?:under|below|less than|no more than|maximum|max|budget(?: of)?|up to|"
        r"between|from|at least|minimum(?: of)?|no less than)\s*"
        r"(?:[^\w\s]\s*|rs\.?\s*|inr\s*|usd\s*)?\d[\d,]*(?:\.\d+)?\s*k?",
        " ",
        required_text,
        flags=re.IGNORECASE,
    )
    terms = {
        token for token in _normalized_tokens(required_text) - _REQUEST_STOP_WORDS
        if len(token) > 1
    }
    terms.difference_update(_category_vocabulary(category, category_terms or []))
    return terms


def _structured_product_fields(product: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    specifications = product.get("specifications")
    if isinstance(specifications, dict):
        fields.extend((str(key), str(value)) for key, value in specifications.items())
    elif isinstance(specifications, list):
        for value in specifications:
            text = str(value)
            key, separator, field_value = text.partition(":")
            fields.append((key.strip(), field_value.strip()) if separator else ("Specification", text))
    for key in ("ram", "storage", "capacity", "size", "color", "colour", "material",
                "connectivity", "features", "resolution", "model", "modelNumber", "sku"):
        value = product.get(key)
        if value is not None:
            fields.append((key, str(value)))
    dimensions = product.get("dimensions")
    if isinstance(dimensions, dict):
        fields.extend((str(key), str(value)) for key, value in dimensions.items())
    tags = product.get("tags")
    if isinstance(tags, list):
        fields.extend(("features", str(tag)) for tag in tags)
    return fields


def _structured_product_text(product: dict[str, Any]) -> str:
    return " ".join(f"{key} {value}" for key, value in _structured_product_fields(product))


def _measurement_base(value: str) -> tuple[str, Decimal] | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*([a-z]+)", value.casefold())
    if not match:
        return None
    amount = Decimal(match.group(1))
    unit = match.group(2)
    units = {
        "tb": ("storage", Decimal(1024 * 1024)),
        "gb": ("storage", Decimal(1024)),
        "mb": ("storage", Decimal(1)),
        "litre": ("volume", Decimal(1000)),
        "litres": ("volume", Decimal(1000)),
        "liter": ("volume", Decimal(1000)),
        "liters": ("volume", Decimal(1000)),
        "l": ("volume", Decimal(1000)),
        "ml": ("volume", Decimal(1)),
        "kg": ("mass", Decimal(1000)),
        "g": ("mass", Decimal(1)),
        "metre": ("length", Decimal(1000)),
        "metres": ("length", Decimal(1000)),
        "meter": ("length", Decimal(1000)),
        "meters": ("length", Decimal(1000)),
        "m": ("length", Decimal(1000)),
        "cm": ("length", Decimal(10)),
        "mm": ("length", Decimal(1)),
        "inch": ("length", Decimal("25.4")),
        "inches": ("length", Decimal("25.4")),
        "in": ("length", Decimal("25.4")),
    }
    unit_info = units.get(unit)
    return (unit_info[0], amount * unit_info[1]) if unit_info else None


def _requirement_is_verified(requirement: dict[str, Any], product: dict[str, Any]) -> bool:
    field_aliases = {
        "ram": {"ram", "memory"},
        "storage": {"storage", "ssd", "hdd"},
        "size": {"size"},
        "color": {"color", "colour"},
        "material": {"material"},
        "feature": {"feature", "features", "connectivity", "resolution", "network"},
        "capacity": {"capacity"},
        "weight": {"weight"},
        "dimensions": {"dimensions", "width", "height", "depth", "screen", "display"},
        "width": {"width", "dimensions"},
        "height": {"height", "dimensions"},
        "depth": {"depth", "dimensions"},
        "resolution": {"resolution", "display", "screen"},
        "power": {"power", "battery"},
        "battery": {"battery", "power"},
        "processor": {"processor", "cpu"},
        "network": {"network", "connectivity"},
        "model": {"model", "modelnumber", "sku"},
    }
    name = str(requirement.get("name", "Specification")).casefold()
    normalized_name_tokens = _normalized_tokens(name)
    aliases = (
        None if name in {"specification", "other"}
        else field_aliases.get(name, normalized_name_tokens or {name})
    )
    all_fields = _structured_product_fields(product)
    selected_fields = [
        (key, value)
        for key, value in all_fields
        if aliases is None
        or re.sub(r"[^a-z0-9]", "", key.casefold()) in aliases
        or (
            re.sub(r"[^a-z0-9]", "", key.casefold()) == "specification"
            and bool(aliases and aliases.intersection(_normalized_tokens(value)))
        )
    ]
    if not selected_fields:
        return False
    structured = " ".join(f"{key} {value}" for key, value in selected_fields)
    requested = str(requirement.get("value", "")).strip()
    value_aliases = {
        "wooden": "wood",
        "wood": "wooden",
        "litre": "liter",
        "litres": "liters",
        "colour": "color",
        "grey": "gray",
    }
    normalized_requested = re.sub(r"[^a-z0-9]", "", requested.casefold())
    normalized_evidence = re.sub(r"[^a-z0-9]", "", structured.casefold())
    if not normalized_requested:
        return False
    if normalized_requested in normalized_evidence:
        return True
    alias = value_aliases.get(requested.casefold())
    normalized_alias = re.sub(r"[^a-z0-9]", "", alias.casefold()) if alias else ""
    if normalized_alias and normalized_alias in normalized_evidence:
        return True
    requested_measurement = _measurement_base(requested)
    if not requested_measurement:
        return False
    for value_match in re.finditer(r"\d+(?:\.\d+)?\s*[a-z]+", structured.casefold()):
        evidence_measurement = _measurement_base(value_match.group())
        if not evidence_measurement or evidence_measurement[0] != requested_measurement[0]:
            continue
        if (
            evidence_measurement[1] >= requested_measurement[1]
            if requirement.get("operator") == "minimum"
            else evidence_measurement[1] == requested_measurement[1]
        ):
            return True
    return False


def _exclusion_is_verified(exclusion: dict[str, str], product: dict[str, Any]) -> tuple[bool, bool]:
    structured = _structured_product_text(product)
    normalized_evidence = re.sub(r"[^a-z0-9]", "", structured.casefold())
    name_tokens = _normalized_tokens(exclusion["name"])
    value = re.sub(r"[^a-z0-9]", "", exclusion["value"].casefold())
    attribute_present = bool(name_tokens.intersection(_normalized_tokens(structured)))
    excluded_value_present = bool(value and value in normalized_evidence)
    return attribute_present, excluded_value_present


def _category_matches_product(
    product_category: str,
    category: str,
    category_terms: list[str],
    explicit: bool,
    product_evidence: str = "",
) -> bool:
    if not category and not category_terms:
        return True
    normalized_category = re.sub(r"[^a-z0-9]+", "-", category.casefold()).strip("-")
    normalized_product_category = re.sub(
        r"[^a-z0-9]+", "-", product_category.casefold()
    ).strip("-")
    if explicit and not category_terms and normalized_category in {
        "mens-watches", "womens-watches", "mens-shoes", "womens-shoes",
        "mens-shirts", "womens-dresses",
    }:
        return normalized_product_category == normalized_category

    requested_families = set().union(
        *(_category_families(term) for term in category_terms)
    ) if category_terms else set()
    if not requested_families:
        requested_families = _category_families(category)
    if "clothing" in requested_families:
        requested_families.update({"shirts", "dresses"})

    product_families = _category_families(product_category)
    if product_families.intersection({"furniture", "appliances", "audio"}):
        product_families.update(_category_families(product_evidence))
    if requested_families:
        return bool(requested_families.intersection(product_families))
    requested_tokens = set().union(
        *(_normalized_tokens(value) for value in [category, *category_terms])
    )
    product_tokens = _normalized_tokens(
        " ".join((product_category, product_evidence))
    )
    if requested_tokens:
        return bool(requested_tokens.intersection(product_tokens))
    return normalized_product_category == normalized_category


def parse_intent(payload: IntentRequest) -> dict[str, Any]:
    text = payload.request
    lowered = text.lower()
    mandatory_text = _mandatory_query_text(text)
    requirements = _extract_requirements(mandatory_text)
    exclusions = _extract_exclusions(text)
    for exclusion in exclusions:
        requirements = [
            requirement for requirement in requirements
            if str(requirement.get("value", "")).casefold() != exclusion["value"].casefold()
        ]
    inferred_category = ""
    category_terms: list[str] = []
    for pattern, category, term in _CATEGORY_PATTERNS:
        if re.search(pattern, mandatory_text, re.IGNORECASE):
            inferred_category = category
            category_terms = [term]
            break

    budget_match = re.search(
        r"(?:under|below|less than|no more than|maximum|max|budget(?: of)?|up to)\s*"
        r"(?:₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?",
        text,
        re.IGNORECASE,
    )
    budget = payload.maximumBudget
    if budget_match:
        parsed = float(budget_match.group(1).replace(",", ""))
        budget = parsed * (1000 if budget_match.group(2) else 1)

    minimum_budget = None
    minimum_match = re.search(
        r"(?:at least|no less than|minimum(?: of)?|from)\s*(?:₹|rs\.?|inr|\$|usd)\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*(k)?",
        text,
        re.IGNORECASE,
    )
    range_match = re.search(
        r"\b(?:between|from)\s*(?:₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)\s*"
        r"(?:and|to|-)\s*(?:₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if range_match:
        minimum_budget = float(range_match.group(1).replace(",", ""))
        budget = float(range_match.group(2).replace(",", ""))
    elif minimum_match:
        minimum_budget = float(minimum_match.group(1).replace(",", ""))
        if minimum_match.group(2):
            minimum_budget *= 1000

    currency = payload.currency
    if re.search(r"\$|usd|dollars?", text, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"₹|rs\.?|inr|rupees?", text, re.IGNORECASE):
        currency = "INR"

    quantity_match = re.search(
        r"\b(?:buy|get|need|want|find|quantity(?: of)?|qty)\s+(\d+)\s*"
        r"(?:units?|items?|pieces?|pairs?)?\b",
        lowered,
    )
    if not quantity_match:
        quantity_match = re.search(
            r"\b(\d+)\s+(?:units?|items?|pieces?|pairs?|laptops?|phones?|"
            r"smartphones?|tablets?|watches?|shoes?|shirts?|tables?)\b",
            lowered,
        )
    quantity = int(quantity_match.group(1)) if quantity_match else 1
    category = payload.category or inferred_category
    return {
        "request": text,
        "category": category,
        "categoryIsExplicit": bool(payload.category),
        "categoryTerms": category_terms,
        "requirements": requirements,
        "exclusions": exclusions,
        "mandatoryTerms": sorted(
            _mandatory_request_terms(text, requirements, category, category_terms)
        ),
        "minimumBudget": minimum_budget,
        "maximumBudget": budget,
        "quantity": quantity,
        "currency": currency,
        "trustedSellersOnly": payload.trustedSellersOnly,
        "platformId": payload.platformId,
        "excludeAccessories": bool(
            re.search(
                r"\b(?:do not|don't|no)\s+add\s+accessories\b|"
                r"\b(?:without|excluding|exclude|no)\s+accessories\b",
                lowered,
            )
        ),
    }


def build_verification(
    items: list[dict[str, Any]],
    intent: dict[str, Any],
    order_version: int,
    converted_total: float | None = None,
    exchange_rate: float | None = None,
    exchange_rate_date: str | None = None,
) -> dict[str, Any]:
    totals = cart_price(items)
    requirements = intent.get("requirements", [])
    requested_category = str(intent.get("category", "")).strip()
    category_terms = (
        intent.get("categoryTerms", [])
        if isinstance(intent.get("categoryTerms", []), list)
        else []
    )
    category_is_explicit = bool(
        intent.get("categoryIsExplicit", bool(requested_category))
    )
    mismatched_products = [
        item["product"]
        for item in items
        if not _category_matches_product(
            str(item["product"].get("category", "")),
            requested_category,
            category_terms,
            category_is_explicit,
            _product_category_evidence(item["product"]),
        )
    ]
    category_ok = not mismatched_products
    accessory_items = [
        item["product"].get("title", "")
        for item in items
        if re.search(r"\b(accessory|accessories|case|charger|cable|adapter)\b", item["product"].get("title", ""), re.I)
    ]
    budget_currency = intent.get("currency", "USD")
    try:
        budget_amount = Decimal(str(intent.get("maximumBudget", 0) or 0))
        has_budget = budget_amount.is_finite() and budget_amount > 0
    except (InvalidOperation, TypeError, ValueError):
        budget_amount = Decimal("0")
        has_budget = False

    try:
        converted_budget_total = Decimal(str(converted_total))
        within_budget = (
            has_budget
            and converted_budget_total.is_finite()
            and converted_budget_total <= budget_amount
        )
    except (InvalidOperation, TypeError, ValueError):
        within_budget = False
    if not has_budget:
        price_reason = "A valid customer budget is unavailable; the order cannot be safely compared."
    elif converted_total is None:
        price_reason = (
            f"Exchange rate unavailable; the USD order total could not be safely "
            f"compared with the {budget_currency} budget."
        )
    elif not within_budget:
        price_reason = (
            f"Estimated total ${totals['total']:.2f} converts to "
            f"{budget_currency} {converted_total:.2f}, exceeding the "
            f"{budget_currency} budget of {budget_amount:.2f}."
        )
    else:
        price_reason = (
            f"Estimated total ${totals['total']:.2f} converts to "
            f"{budget_currency} {converted_total:.2f}, within the "
            f"{budget_currency} budget of {budget_amount:.2f}."
        )
    if exchange_rate is not None:
        price_reason += (
            f" Conversion rate: 1 USD = {exchange_rate} {budget_currency} "
            f"(rate date: {exchange_rate_date})."
        )

    checks = [
        {
            "name": "Product type",
            "status": "Passed" if category_ok else "Failed",
            "reason": (
                "Cart product category matches the purchase policy."
                if category_ok
                else (
                    "These cart products do not match the requested category "
                    f"'{requested_category or 'unspecified'}': "
                    + "; ".join(
                        f"'{product.get('title') or 'Untitled product'}' "
                        f"(catalogue category: "
                        f"'{product.get('category') or 'not provided'}')"
                        for product in mismatched_products
                    )
                    + ". Remove or replace them, or review the purchase policy."
                )
            ),
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
            "status": "Passed" if within_budget else "Failed",
            "reason": price_reason,
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
        "budgetComparison": {
            "amount": converted_total,
            "currency": budget_currency,
            "exchangeRate": exchange_rate,
            "exchangeRateBase": "USD",
            "exchangeRateQuote": budget_currency,
            "exchangeRateDate": exchange_rate_date,
        },
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
    stored = json_load(row_value(order, "cart_json", default=[]), default=[])
    if not isinstance(stored, list):
        return False
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
    stored_items = json_load(row_value(order, "cart_json", default=[]), default=[])
    if not isinstance(stored_items, list):
        return False
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

        stored_items = json_load(row_value(latest_order, "cart_json", default=[]), default=[])
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
    if not isinstance(result, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The product catalogue returned an invalid category list.",
        )
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An intent object is required.",
        )

    query = intent.get("request", "")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid shopping request is required.",
        )
    if intent.get("platformId", "dummyjson") != "dummyjson":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the DummyJSON Demo Store is supported for product recommendations.",
        )

    raw_category = intent.get("category") or ""
    category_explicit_value = intent.get("categoryIsExplicit")
    category_is_explicit = (
        category_explicit_value
        if isinstance(category_explicit_value, bool)
        else bool(raw_category)
    )
    if raw_category and (
        not isinstance(raw_category, str)
        or not re.fullmatch(r"[a-z0-9-]{1,80}", raw_category)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid product category.",
        )

    raw_currency = str(intent.get("currency", "USD")).upper()
    parser_currency = raw_currency if raw_currency in {"USD", "INR"} else "USD"
    try:
        parser_budget = Decimal(str(intent.get("maximumBudget", 1) or 1))
        if not parser_budget.is_finite() or parser_budget <= 0:
            parser_budget = Decimal("1")
    except (InvalidOperation, TypeError, ValueError):
        parser_budget = Decimal("1")
    parsed_request = parse_intent(IntentRequest(
        request=query,
        maximumBudget=float(parser_budget),
        currency=parser_currency,
        trustedSellersOnly=bool(intent.get("trustedSellersOnly", False)),
    ))
    parsed_price_range = bool(re.search(
        r"\b(?:under|below|less than|no more than|maximum|max|budget(?: of)?|"
        r"up to|between|from)\b\s*(?:[^\w\s]\s*|rs\.?\s*|inr\s*|usd\s*)?\d",
        query,
        re.IGNORECASE,
    ))
    interpretation = await interpret_product_request(query)

    if category_is_explicit and raw_category:
        category = raw_category
        normalized_raw_category = raw_category.casefold()
        parsed_category_families = _category_families(parsed_request["category"])
        raw_category_families = _category_families(raw_category)
        if (
            parsed_category_families.intersection(raw_category_families)
            and normalized_raw_category not in {
                "mens-watches", "womens-watches", "mens-shoes",
                "womens-shoes", "mens-shirts", "womens-dresses",
            }
        ):
            category_terms = parsed_request["categoryTerms"]
        else:
            category_terms = []
        if interpretation:
            interpretation_families = _category_families(
                " ".join((interpretation.category, *interpretation.category_terms))
            )
            if not raw_category_families or raw_category_families.intersection(interpretation_families):
                category_terms.extend(interpretation.category_terms)
    else:
        category = (
            interpretation.category
            if interpretation and interpretation.category
            else parsed_request["category"] or raw_category
        )
        category_terms = [
            *parsed_request["categoryTerms"],
            *(interpretation.category_terms if interpretation else []),
        ] or intent.get("categoryTerms", [])
    if not isinstance(category_terms, list):
        category_terms = []
    category_terms = list(dict.fromkeys(
        str(term).strip()
        for term in category_terms
        if str(term).strip()
    ))

    client_requirements = intent.get("requirements", [])
    if not isinstance(client_requirements, list):
        client_requirements = []
    requirements = [
        requirement for requirement in client_requirements
        if isinstance(requirement, dict)
    ]
    requirements.extend(parsed_request["requirements"])
    unique_requirements: dict[tuple[str, str], dict[str, Any]] = {}
    for requirement in requirements:
        key = (
            str(requirement.get("name", "Specification")).casefold(),
            re.sub(r"[^a-z0-9]", "", str(requirement.get("value", "")).casefold()),
        )
        unique_requirements.setdefault(key, requirement)
    requirements = list(unique_requirements.values())

    client_exclusions = intent.get("exclusions", [])
    if not isinstance(client_exclusions, list):
        client_exclusions = []
    exclusions = [
        exclusion for exclusion in client_exclusions
        if isinstance(exclusion, dict)
    ] + parsed_request["exclusions"]
    exclusions = list({
        (
            str(exclusion.get("name", "Feature")).casefold(),
            str(exclusion.get("value", "")).casefold(),
        ): exclusion
        for exclusion in exclusions
    }.values())
    excluded_values = {
        str(exclusion.get("value", "")).casefold()
        for exclusion in exclusions
    }
    requirements = [
        requirement for requirement in requirements
        if str(requirement.get("value", "")).casefold() not in excluded_values
    ]
    intent = dict(intent)
    intent["category"] = category
    intent["categoryTerms"] = category_terms
    intent["categoryIsExplicit"] = bool(category_is_explicit and raw_category)
    intent["requirements"] = requirements
    intent["exclusions"] = exclusions
    if parsed_price_range:
        intent["maximumBudget"] = parsed_request["maximumBudget"]
    elif (
        interpretation
        and interpretation.maximum_budget is not None
        and re.search(r"\b(?:budget|spend|afford|pay)\b", query, re.IGNORECASE)
    ):
        interpreted_budget = Decimal(str(interpretation.maximum_budget))
        if interpreted_budget.is_finite() and interpreted_budget > 0:
            intent["maximumBudget"] = float(interpreted_budget)
    if parsed_request["minimumBudget"] is not None:
        intent["minimumBudget"] = parsed_request["minimumBudget"]
    elif "minimumBudget" not in intent:
        intent["minimumBudget"] = None
    if re.search(r"\$|usd|dollars?", query, re.IGNORECASE):
        intent["currency"] = "USD"
    elif re.search(r"₹|rs\.?|inr|rupees?", query, re.IGNORECASE):
        intent["currency"] = "INR"
    elif raw_currency:
        intent["currency"] = raw_currency
    if parsed_request["quantity"] != 1:
        intent["quantity"] = parsed_request["quantity"]
    intent["excludeAccessories"] = bool(
        intent.get("excludeAccessories") or parsed_request["excludeAccessories"]
    )

    interpreted_search_terms = (
        [
            interpretation.product_type,
            *interpretation.search_terms,
            *(
                f"{attribute.value} {attribute.name}"
                for attribute in interpretation.attributes
            ),
        ]
        if interpretation
        else []
    )
    provider_search_terms = interpreted_search_terms or [
        *category_terms,
        query,
    ]
    products = await _fetch_catalogue_products(provider_search_terms)
    catalogue_brands = {
        str(product.get("brand", "")).strip()
        for product in products
        if isinstance(product, dict) and str(product.get("brand", "")).strip()
    }
    requested_brands = _extract_brands(_mandatory_query_text(query), catalogue_brands)
    preferred_brands = (
        interpretation.brand_preferences
        if interpretation
        else []
    )
    mandatory_terms = _mandatory_request_terms(
        query, requirements, category, category_terms
    )

    keywords = {
        token for token in _normalized_tokens(query) - _REQUEST_STOP_WORDS
        if not token.isdigit()
    }
    for requirement in requirements:
        keywords.difference_update(_normalized_tokens(requirement.get("value", "")))
        keywords.difference_update(_normalized_tokens(requirement.get("name", "")))
    keywords.difference_update(_normalized_tokens(str(intent.get("maximumBudget", ""))))
    keywords.difference_update(_normalized_tokens(str(intent.get("minimumBudget", ""))))
    keywords.difference_update(_normalized_tokens(" ".join(requested_brands)))
    keywords.difference_update(_normalized_tokens(category))
    for term in category_terms:
        keywords.difference_update(_normalized_tokens(term))

    currency = str(intent.get("currency", "USD")).upper()

    try:
        budget_decimal = Decimal(str(intent.get("maximumBudget", 0) or 0))
        has_budget = budget_decimal.is_finite() and budget_decimal > 0
    except (InvalidOperation, TypeError, ValueError):
        budget_decimal = Decimal("0")
        has_budget = False
    invalid_maximum_budget = (
        intent.get("maximumBudget") is not None
        and not has_budget
    )

    try:
        minimum_budget = Decimal(str(intent.get("minimumBudget")))
        has_minimum_budget = minimum_budget.is_finite() and minimum_budget > 0
    except (InvalidOperation, TypeError, ValueError):
        minimum_budget = Decimal("0")
        has_minimum_budget = False
    invalid_minimum_budget = (
        intent.get("minimumBudget") is not None
        and not has_minimum_budget
    )

    try:
        quantity = int(intent.get("quantity", 1))
        quantity_is_valid = 1 <= quantity <= 99
        if not quantity_is_valid:
            quantity = 1
    except (TypeError, ValueError):
        quantity_is_valid = False
        quantity = 1

    product_currencies = {
        str(product.get("currency") or "USD").upper()
        for product in products
        if isinstance(product, dict)
    }
    exchange_rates: dict[str, dict[str, Any] | None] = {}
    for product_currency in product_currencies:
        exchange_rates[product_currency] = await get_exchange_rate(product_currency, currency)

    enriched = []
    rejection_reasons: set[str] = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        product_category = str(product.get("category", ""))
        title = str(product.get("title", ""))
        brand = str(product.get("brand", ""))
        tags = product.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        specifications_text = _structured_product_text(product)
        product_text = " ".join(
            [title, brand, product_category, specifications_text]
            + [str(tag) for tag in tags]
        )
        product_tokens = _normalized_tokens(product_text)
        interpreted_relevance = 0.0
        if interpretation:
            for phrase in (
                interpretation.product_type,
                *interpretation.search_terms,
                *(
                    f"{attribute.value} {attribute.name}"
                    for attribute in interpretation.attributes
                ),
            ):
                phrase_tokens = _normalized_tokens(phrase) - _REQUEST_STOP_WORDS
                if phrase_tokens:
                    interpreted_relevance = max(
                        interpreted_relevance,
                        len(phrase_tokens.intersection(product_tokens)) / len(phrase_tokens),
                    )

        matched_category = _category_matches_product(
            product_category,
            category,
            category_terms,
            bool(category_is_explicit),
            _product_category_evidence(product),
        )
        if not matched_category:
            rejection_reasons.add(f"category {category or ' '.join(category_terms)}")
            continue

        if intent.get("excludeAccessories") and re.search(
            r"\b(accessory|accessories|case|charger|cable|adapter)\b",
            title,
            re.IGNORECASE,
        ):
            rejection_reasons.add("accessory exclusion")
            continue

        brand_matched = _product_brand_matches(requested_brands, product)
        keyword_hits = len(keywords.intersection(product_tokens))
        name_relevance = max(
            keyword_hits / len(keywords) if keywords else 0.0,
            interpreted_relevance,
        )
        preferred_brand_matched = any(
            _product_brand_matches([brand], product) is True
            for brand in preferred_brands
        )

        try:
            price_decimal = Decimal(str(product["price"]))
            price_is_valid = price_decimal.is_finite() and price_decimal >= 0
        except (KeyError, InvalidOperation, TypeError, ValueError):
            price_decimal = Decimal("0")
            price_is_valid = False

        product_currency = str(product.get("currency") or "USD").upper()
        rate_info = exchange_rates.get(product_currency)
        estimated_totals = (
            cart_price([{"product": {"price": float(price_decimal)}, "quantity": quantity}])
            if price_is_valid
            else None
        )
        converted_price = (
            convert_currency_amount(price_decimal, product_currency, currency, rate_info)
            if price_is_valid
            else None
        )
        converted_shipping = (
            convert_currency_amount(estimated_totals["shipping"], product_currency, currency, rate_info)
            if estimated_totals
            else None
        )
        converted_tax = (
            convert_currency_amount(estimated_totals["tax"], product_currency, currency, rate_info)
            if estimated_totals
            else None
        )
        converted_total = (
            convert_currency_amount(estimated_totals["total"], product_currency, currency, rate_info)
            if estimated_totals
            else None
        )
        comparison_amount = converted_total["amount"] if converted_total else None
        budget_matches = (
            comparison_amount is not None
            and Decimal(str(comparison_amount)) <= budget_decimal
        ) if has_budget and comparison_amount is not None else None
        minimum_budget_matches = (
            converted_price is not None
            and Decimal(str(converted_price["amount"])) >= minimum_budget
        ) if has_minimum_budget else True

        matches = []
        for requirement in requirements:
            name = str(requirement.get("name", "Specification"))
            requested = str(requirement.get("value", ""))
            verified = _requirement_is_verified(requirement, product)
            if verified:
                match_status = "Matched"
                explanation = (
                    "The requested value is present in structured product catalogue data."
                )
            else:
                match_status = "Not available for verification"
                explanation = (
                    "The public catalogue does not provide structured technical "
                    "information to verify this specification."
                )

            matches.append({
                "name": name,
                "requested": requested,
                "status": match_status,
                "explanation": explanation,
            })

        all_specs_mentioned = bool(matches) and all(
            match["status"] == "Matched" for match in matches
        )
        exclusion_checks = [
            _exclusion_is_verified(exclusion, product)
            for exclusion in exclusions
            if isinstance(exclusion.get("name"), str)
            and isinstance(exclusion.get("value"), str)
        ]
        constraints = []
        if intent.get("excludeAccessories"):
            constraints.append({
                "name": "No accessories",
                "status": "Matched",
                "explanation": "No excluded accessory was found in the product title.",
            })
        if intent.get("trustedSellersOnly"):
            constraints.append({
                "name": "Trusted seller",
                "status": "Not available for verification",
                "explanation": "Seller identity and trust status are not supplied by the catalogue.",
            })

        exclusions_satisfied = (
            len(exclusion_checks) == len(exclusions)
            and all(attribute_present and not excluded_value_present
                    for attribute_present, excluded_value_present in exclusion_checks)
        )
        failed_requirements = []
        if requested_brands and brand_matched is not True:
            failed_requirements.extend(f"brand {brand}" for brand in requested_brands)
        failed_requirements.extend(
            f"{match['name']} {match['requested']}"
            for match in matches
            if match["status"] != "Matched"
        )
        if not exclusions_satisfied:
            failed_requirements.extend(
                f"excluded characteristic {exclusion.get('value', '')}"
                for exclusion in exclusions
            )
        if has_budget and budget_matches is not True:
            failed_requirements.append(
                f"maximum budget in {currency}"
                if comparison_amount is not None
                else f"currency conversion to {currency}"
            )
        if has_minimum_budget and not minimum_budget_matches:
            failed_requirements.append(f"minimum budget in {currency}")
        if invalid_maximum_budget:
            failed_requirements.append("valid maximum budget")
        if invalid_minimum_budget:
            failed_requirements.append("valid minimum budget")
        if not quantity_is_valid:
            failed_requirements.append("valid requested quantity")
        if not price_is_valid:
            failed_requirements.append("valid catalogue price")
        if failed_requirements:
            rejection_reasons.update(failed_requirements)
            continue

        score_numerator = 35 * name_relevance
        score_denominator = 35
        if requested_brands:
            score_denominator += 25
            score_numerator += 25 if brand_matched else 0
        if category:
            score_denominator += 15
            score_numerator += 15 if matched_category else 0
        if requirements:
            spec_evidence = sum(
                0.5 if match["status"] == "Mentioned in catalogue (unverified)" else 0
                for match in matches
            ) / len(requirements)
            score_denominator += 20
            score_numerator += 20 * spec_evidence
        if has_budget:
            score_denominator += 15
            score_numerator += 15 if budget_matches is True else 0
        if constraints:
            constraint_evidence = sum(
                constraint["status"] == "Matched" for constraint in constraints
            ) / len(constraints)
            score_denominator += 10
            score_numerator += 10 * constraint_evidence
        if preferred_brands:
            score_denominator += 10
            score_numerator += 10 if preferred_brand_matched else 0
        percentage = round(score_numerator / score_denominator * 100)

        requested_name_matched = bool(mandatory_terms) and mandatory_terms.issubset(product_tokens)
        requested_brand_matched = not requested_brands or brand_matched is True
        requested_specs_satisfied = not requirements or all_specs_mentioned
        requested_constraints_satisfied = all(
            constraint["status"] == "Matched" for constraint in constraints
        )
        budget_eligible = not has_budget or budget_matches is True
        currency_verified = not has_budget or comparison_amount is not None
        category_eligible = not category or matched_category
        exact_match = (
            requested_name_matched
            and requested_brand_matched
            and category_eligible
            and requested_specs_satisfied
            and requested_constraints_satisfied
            and budget_eligible
            and currency_verified
        )
        relevant = (
            name_relevance > 0
            or brand_matched is True
            or preferred_brand_matched
        )
        match_type = (
            "Exact Match" if exact_match
            else "Partial Match" if relevant or matched_category
            else "No Match"
        )

        if has_budget and (converted_total is None or not price_is_valid):
            recommendation_status = "Exchange Rate Unavailable"
        elif has_budget and budget_matches is False:
            recommendation_status = "Budget Exceeded"
        elif category and not matched_category:
            recommendation_status = "Category Mismatch"
        elif requirements and not all_specs_mentioned:
            recommendation_status = "Specifications Unverified"
        elif any(constraint["status"] != "Matched" for constraint in constraints):
            recommendation_status = "Constraint Verification Pending"
        elif match_type != "Exact Match":
            recommendation_status = match_type
        else:
            recommendation_status = "Matches Requirements"

        verification_status = (
            "Currency Verification Pending" if has_budget and not currency_verified
            else "Specifications Unverified" if requirements
            else "Constraint Verification Pending" if not requested_constraints_satisfied
            else "Verified"
        )
        ranking_tier = (
            0 if exact_match
            else 1 if (
                relevant
                and budget_eligible
                and currency_verified
                and category_eligible
                and verification_status == "Verified"
            )
            else 2 if relevant and budget_matches is False
            else 3
        )
        exchange_rate = converted_total["rate"] if converted_total else None
        exchange_rate_date = converted_total["date"] if converted_total else None
        enriched.append({
            "product": product,
            "analysis": {
                "percentage": percentage,
                "matchType": match_type,
                "rankingTier": ranking_tier,
                "nameRelevance": round(name_relevance, 4),
                "nameMatched": requested_name_matched,
                "requestedBrand": requested_brands[0] if requested_brands else None,
                "brandMatched": brand_matched,
                "preferredBrandMatched": preferred_brand_matched if preferred_brands else None,
                "brandMatchStatus": (
                    "Matched" if brand_matched is True
                    else "Not matched" if brand_matched is False
                    else "Not requested" if not requested_brands
                    else "Not available for verification"
                ),
                "verificationStatus": verification_status,
                "categoryMatched": matched_category,
                "specificationsMatched": all_specs_mentioned if requirements else None,
                "budgetMatched": budget_matches,
                "budgetCurrency": currency if has_budget else None,
                "budgetAmount": float(budget_decimal) if has_budget else None,
                "cataloguePrice": float(price_decimal) if price_is_valid else None,
                "catalogueCurrency": product_currency,
                "convertedPrice": converted_price["amount"] if converted_price else None,
                "convertedShipping": converted_shipping["amount"] if converted_shipping else None,
                "convertedTax": converted_tax["amount"] if converted_tax else None,
                "comparableTotal": comparison_amount,
                "comparisonCurrency": currency,
                "exchangeRate": exchange_rate,
                "exchangeRateBase": product_currency,
                "exchangeRateQuote": currency,
                "exchangeRateDate": exchange_rate_date,
                "matches": matches,
                "constraints": constraints,
                "status": recommendation_status,
            },
        })

    status_priority = {
        "Matches Requirements": 0,
        "Specifications Unverified": 1,
        "Budget Exceeded": 2,
        "Exchange Rate Unavailable": 3,
        "Category Mismatch": 4,
    }
    enriched.sort(
        key=lambda item: (
            item["analysis"]["rankingTier"],
            status_priority.get(item["analysis"]["status"], 5),
            -item["analysis"]["percentage"],
        ),
    )

    add_audit(
        user["id"],
        "Product API data retrieved",
        f"Retrieved {len(enriched)} relevant recommendation product(s).",
    )

    return {
        "recommendations": enriched,
        "total": len(enriched),
        "message": (
            None if enriched
            else (
                "No products matched all mandatory requirements"
                + (
                    f": {', '.join(sorted(rejection_reasons))}"
                    if rejection_reasons
                    else "."
                )
                + " No requirements were relaxed."
            )
        ),
    }


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
            intent = json.loads(order["intent_json"])
            budget_currency = intent.get("currency", "USD")

            exchange_rate_info = await get_exchange_rate("USD", budget_currency)
            converted_cart_total = convert_currency_amount(
                cart_price(items)["total"],
                "USD",
                budget_currency,
                exchange_rate_info,
            )
            converted_total = (
                converted_cart_total["amount"] if converted_cart_total else None
            )
            exchange_rate = converted_cart_total["rate"] if converted_cart_total else None
            exchange_rate_date = converted_cart_total["date"] if converted_cart_total else None

            checks = build_verification(
                items,
                intent,
                order["version"],
                converted_total=converted_total,
                exchange_rate=exchange_rate,
                exchange_rate_date=exchange_rate_date,
            )
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


@app.get("/api/transactions/{transaction_id}")
def get_transaction_details(
    transaction_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as connection:
        transaction = connection.execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, user["id"]),
        ).fetchone()
        if transaction is None or transaction["status"] != "Completed":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Completed transaction not found.",
            )
        order = connection.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (transaction["order_id"], user["id"]),
        ).fetchone()
        if order is None or order["status"] != "completed":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Completed order details not found.",
            )

    stored_items = json.loads(order["cart_json"])
    intent = json.loads(order["intent_json"])
    platform_id = intent.get("platformId")
    marketplace = (
        "DummyJSON Demo Store"
        if platform_id == "dummyjson"
        else None
    )
    products = []
    for item in stored_items:
        product = item["product"]
        quantity = int(item["quantity"])
        unit_price = float(product["price"])
        products.append({
            "product": product,
            "quantity": quantity,
            "unit_price": unit_price,
            "subtotal": round(unit_price * quantity, 2),
            "provider": product.get("source") or product.get("provider") or "DummyJSON demo catalogue",
            "marketplace": marketplace,
            "product_url": product.get("url") if isinstance(product.get("url"), str) else None,
        })

    verification = json.loads(order["checks_json"]) if order["checks_json"] else None
    totals = verification.get("totals") if isinstance(verification, dict) else None
    if not isinstance(totals, dict):
        totals = cart_price(json.loads(order["cart_json"]))
    checks = verification.get("checks") if isinstance(verification, dict) else None
    if not isinstance(checks, list):
        checks = None

    budget_comparison = (
        verification.get("budgetComparison")
        if isinstance(verification, dict)
        else None
    )
    budget = None
    try:
        maximum_budget = Decimal(str(intent["maximumBudget"]))
        comparison_currency = str(
            (budget_comparison or {}).get("currency") or intent.get("currency") or ""
        )
        comparable_value = (budget_comparison or {}).get("amount")
        comparable_total = (
            Decimal(str(comparable_value)) if comparable_value is not None else None
        )
        if maximum_budget.is_finite() and maximum_budget > 0:
            within_budget_check = next(
                (
                    check for check in checks or []
                    if isinstance(check, dict) and check.get("name") == "Final price"
                ),
                None,
            )
            comparison_is_valid = bool(
                comparable_total is not None
                and comparable_total.is_finite()
                and comparison_currency == intent.get("currency")
            )
            budget_status = "Not available"
            remaining = None
            actual_budget_total = None
            if comparison_is_valid and comparable_total is not None:
                actual_budget_total = float(comparable_total)
                remaining = float(maximum_budget - comparable_total)
                if comparable_total > maximum_budget:
                    budget_status = "Over budget"
                elif within_budget_check and within_budget_check.get("status") == "Passed":
                    budget_status = "Within budget"
                else:
                    budget_status = "Not verified"
            budget = {
                "maximum": float(maximum_budget),
                "currency": str(intent.get("currency") or comparison_currency),
                "actual_total": actual_budget_total,
                "remaining": remaining,
                "status": budget_status,
                "exchange_rate": (budget_comparison or {}).get("exchangeRate"),
                "exchange_rate_base": (budget_comparison or {}).get("exchangeRateBase"),
                "exchange_rate_quote": (budget_comparison or {}).get("exchangeRateQuote"),
                "exchange_rate_date": (budget_comparison or {}).get("exchangeRateDate"),
            }
    except (KeyError, InvalidOperation, TypeError, ValueError):
        budget = None

    detailed_checks = []
    if checks is not None:
        for check in checks:
            if not isinstance(check, dict):
                continue
            detailed_check = dict(check)
            name = check.get("name")
            if name == "Product type":
                detailed_check["expected"] = intent.get("category") or None
                detailed_check["actual"] = sorted({
                    str(item["product"].get("category") or "")
                    for item in stored_items
                    if item["product"].get("category")
                })
            elif name == "Product specifications":
                detailed_check["expected"] = intent.get("requirements") or None
                detailed_check["actual"] = None
            elif name == "Final price":
                detailed_check["expected"] = {
                    "maximum": budget["maximum"],
                    "currency": budget["currency"],
                } if budget else None
                detailed_check["actual"] = {
                    "amount": budget["actual_total"],
                    "currency": budget["currency"],
                } if budget and budget["actual_total"] is not None else None
            elif name == "Shipping and additional fees":
                detailed_check["actual"] = {
                    key: totals.get(key)
                    for key in ("shipping", "tax", "total", "currency")
                }
            detailed_checks.append(detailed_check)

    original_request = str(intent.get("request") or "")
    requested_brands = _extract_brands(original_request)
    persisted_check_names = {
        check.get("name")
        for check in detailed_checks
        if isinstance(check, dict)
    }
    if "Product matches original request" not in persisted_check_names:
        detailed_checks.append({
            "name": "Product matches original request",
            "status": "Not Checked",
            "reason": "The persisted IntentLock verification did not record an overall product-to-request check.",
            "critical": False,
            "expected": original_request or None,
            "actual": None,
        })
    if "Brand requirement compliance" not in persisted_check_names:
        product_brands = sorted({
            str(item["product"].get("brand"))
            for item in stored_items
            if item["product"].get("brand")
        })
        detailed_checks.append({
            "name": "Brand requirement compliance",
            "status": "Not Checked" if requested_brands else "Not Applicable",
            "reason": (
                "The persisted IntentLock verification did not separately verify brand compliance."
                if requested_brands
                else "No brand preference was identified in the saved request."
            ),
            "critical": False,
            "expected": requested_brands or None,
            "actual": product_brands or None,
        })

    return {
        "transaction": {
            "id": transaction["id"],
            "order_id": transaction["order_id"],
            "reference": transaction["id"],
            "provider": transaction["method"],
            "status": transaction["status"],
            "capture_status": "COMPLETED",
            "paypal_capture_id": transaction["paypal_reference"],
            "paypal_order_id": order["paypal_order_id"],
            "amount": transaction["amount"],
            "currency": transaction["currency"],
            "date": transaction["date"],
            "captured_at": order["updated_at"],
            "payer": None,
        },
        "order": {
            "id": order["id"],
            "version": order["version"],
            "status": order["status"],
            "intent": intent,
            "products": products,
            "totals": totals,
            "verification": ({
                **verification,
                "checks": detailed_checks,
            } if isinstance(verification, dict) and checks is not None else None),
            "budget": budget,
        },
    }


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
