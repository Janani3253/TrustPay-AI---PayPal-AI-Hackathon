# TrustPay AI – IntentLock Backend

TrustPay AI provides customer-intent verification for AI-powered autonomous shopping and payments. This backend serves the FastAPI application, IntentLock verification engine, PostgreSQL persistence layer, and PayPal Sandbox payment integration.

---

## 1. Architecture Overview

- **Web Framework:** FastAPI (asynchronous ASGI framework).
- **ASGI Server:** Uvicorn with standard workers.
- **Database Engine (Target):** PostgreSQL 16 via asynchronous engine (`create_async_engine`).
- **PostgreSQL Driver:** Psycopg 3 (`psycopg[binary]`) with asynchronous connection pooling.
- **ORM:** SQLAlchemy 2.x with `AsyncSession` and `DeclarativeBase`.
- **Database Migrations:** Alembic with asynchronous migration runner.
- **Authentication & Security:** Bcrypt password hashing (work factor 12), PyJWT RFC 7519 standard tokens, database-backed `auth_sessions` with instant token revocation.
- **Product Integration Architecture:** Provider-based asynchronous architecture with connection pooling, bounded exponential backoff retries, and high-performance in-memory TTL caching.
- **AI Intent Extraction Engine:** Google Gemini AI integration using official `google-genai` SDK, schema-constrained JSON generation, independent Pydantic evidence validation, and prompt injection defense.
- **Prompt Injection Defense Engine (Phase 5):** Two-layer untrusted content security engine combining deterministic pattern detection across 13 attack taxonomies with semantic Gemini AI analysis, non-downgradable risk invariants, and bounded SHA-256 content caching.
- **Configuration:** Pydantic Settings (`BaseSettings`) loading from `backend/.env`.
- **Dual Architecture (Transitional):** Domain entities are incrementally migrated to PostgreSQL. In Phase 2, Authentication and User Management were fully migrated to PostgreSQL with transparent SQLite user mirroring. In Phase 3, Product Provider Integration was modularized with bounded caching. In Phase 4, natural-language intent extraction is powered by Gemini AI with strict evidence verification.

---

## 2. Current Migration Status

### Phase 1 – Backend Foundation & PostgreSQL Database Architecture: COMPLETED
- PostgreSQL async connection pooling, SQLAlchemy 2.x Base, and Alembic migrations established.
- Centralized configuration with credential safety and health monitoring (`/health`, `/api/health`).

### Phase 2 – Authentication & User Management: COMPLETED
- **PostgreSQL Models:** `User` (`users` table) and `AuthSession` (`auth_sessions` table) created via Alembic revision `0002_create_users_and_auth_sessions`.
- **Password Security:** Standard Bcrypt hashing with configurable cost factor (`BCRYPT_ROUNDS=12`). Supports backward-compatible verification and seamless auto-rehashing of legacy PBKDF2 (`salt:derived`) passwords upon login.
- **Token Management:** Standard JWT tokens signed with `JWT_SECRET_KEY` using HS256, carrying standard claims (`sub`, `jti`, `iss`, `aud`, `exp`).
- **Server-Side Session Revocation:** Logout explicitly invalidates the session (`jti`) in PostgreSQL (`revoked_at` timestamp), immediately revoking access.
- **Dual Compatibility Bridge:** When users register in PostgreSQL, their identity is synchronized into the legacy SQLite database (`trustpay.db`) with identical integer primary keys (`id`), ensuring existing SQLite-backed cart, order, and audit endpoints continue functioning without foreign-key errors.
- **Legacy Migration Script:** `backend/scripts/migrate_legacy_users.py` safely inspects, plans, and transfers legacy SQLite users to PostgreSQL with conflict detection and identity preservation.

### Phase 3 – Product Provider Integration & Catalog Management: COMPLETED
- **Provider Architecture:** Implemented `BaseProductProvider` abstract interface, concrete `DummyJSONProvider` adapter, `ProviderRegistry`, and unconfigured stubs (`AmazonProvider`, `FlipkartProvider`, `MyntraProvider`).
- **Live Upstream Provider:** Real, asynchronous HTTPX integration with DummyJSON (`https://dummyjson.com`), supporting catalogue listing, keyword search, category filtering, individual product retrieval, and dynamic category index extraction.
- **Resilience & Fault Tolerance:** Connection pooling, bounded exponential backoff retries (max 2 retries on transient connection errors/5xx, no retries on 4xx), and clear mapped exceptions.
- **Product Data Normalization:** Strict schema compliance with React frontend (`ProductApiProduct`, `ProductApiListResponse`, `ProductCategory`). Preserves integer primary keys, accurate USD currency representation (no fabricated conversions), and transparent unknown/demo seller identification.
- **In-Memory TTL Cache:** High-performance, bounded asynchronous cache (`ProductCache`) with configurable TTL (`PRODUCT_CACHE_TTL_SECONDS=300`, `PRODUCT_CATEGORY_CACHE_TTL_SECONDS=1800`), LRU eviction at capacity (`PRODUCT_CACHE_MAX_ENTRIES=500`), and automatic cache pre-warming.
- **Recommendation Compatibility:** Maintained complete backward compatibility for `/api/recommendations/search` (supporting both `POST` and `GET`).

### Phase 4 – Gemini AI Intent Extraction & Verification Foundation: COMPLETED
- **Official Google Gen AI SDK:** Integrated official `google-genai` SDK with native asynchronous client calls (`client.aio.models.generate_content`).
- **Structured Schema-Constrained Output:** Configured generation with `response_mime_type="application/json"` and Pydantic schema constraint (`StructuredIntentExtraction`).
- **Independent Evidence Validation:** Built `IntentValidationService` to verify that every extracted specification, budget, preference, and exclusion is directly substantiated by evidence in the customer's original text.
- **Ambiguity & Conflict Handling:** Automated detection of conflicting constraints, missing product types, and ambiguous requests, triggering clarification questions without silently fabricating data.
- **AI Safety & Prompt Injection Defense:** Strict system prompt isolation treating customer instructions as untrusted data input, preventing budget override attacks or unauthorized payment claims.
- **Frontend Contract Compatibility:** `POST /api/intent/parse` returns a validated response fully satisfying the React frontend's `PurchaseIntent` interface.

### Phase 5 – Prompt Injection Detection & Untrusted Content Security Engine: COMPLETED
- **Two-Layer Detection Engine:** Built a defense-in-depth security analyzer combining high-speed deterministic regex/rule inspection with Google Gemini semantic analysis.
- **13 Attack Taxonomies Covered:** Detection across Instruction Override, Budget Manipulation, Cart Manipulation, Purchase Bypass, Payment Manipulation, Charge Concealment, Data Exfiltration, Secret Extraction, System Prompt Extraction, Tool Execution, HTML Hidden Instructions, Encoded Instructions, and Role Manipulation.
- **False-Positive Immunity:** Precompiled regular expressions engineered with word boundaries and contextual filters to guarantee benign marketing language ("Active noise cancellation ignores outside noise", "adds convenience", "no hidden fees") is never falsely flagged.
- **Content Normalizer & De-obfuscation:** Unicode NFKC normalization, zero-width character stripping, hidden HTML element/comment inspection, and bounded Base64/percent-encoding decoders.
- **Core Invariant Enforcement:** Gemini can identify additional semantic threats or upgrade risk levels, but can NEVER suppress or downgrade a deterministic security finding.
- **Backend-Controlled Product Retrieval:** `POST /api/security/analyze-product` fetches authentic product metadata directly from backend providers, preventing client-side content spoofing.

### Phase 6 – PostgreSQL Shopping Cart Management: COMPLETED
- **PostgreSQL Cart & Items Models:** `Cart` (`carts` table) and `CartItem` (`cart_items` table) created via Alembic revision `0003_create_carts_and_cart_items`.
- **Authoritative Backend Pricing:** Client-provided prices are never trusted; prices are resolved from catalog data and stored as exact Decimals.
- **Cart Mutation Versioning:** Every cart addition, quantity update, or deletion atomically increments the cart `version` to detect concurrent checkouts and stale verifications.
- **Dual Compatibility Mirroring:** Cart mutations seamlessly sync into SQLite `cart_items` for legacy compatibility.
- **Migration CLI:** `backend/scripts/migrate_legacy_cart.py` migrates legacy SQLite cart items into PostgreSQL with conflict resolution and dry-run safety.

### Phase 7 – Deterministic IntentLock Verification Engine: COMPLETED
- **Core IntentLock Engine:** Deterministic rule evaluation implemented in `IntentLockEngine`.
- **Zero-AI Payment Authority Invariant:** Gemini AI extracts requirements, but CANNOT authorize payment or override deterministic rules.
- **Multi-Vector Verification Checks:**
  1. *Cart Version & Integrity Check:* Rejects verification if the cart mutated.
  2. *Exact Budget Check:* Decimal math ensures total <= maximumBudget; rejects currency mismatches.
  3. *Contextual Spec Verification:* Natural language RAM & storage extraction with normalized units (GB/TB) and bound regexes preventing RAM/storage collisions.
  4. *Security Policy Scan:* Enforces that no item in the cart contains `SUSPICIOUS` or `MALICIOUS` findings.
  5. *Negative Exclusion Rules:* Verifies cart items do not contain excluded terms, brands, or categories.
- **Verification Endpoint:** `POST /api/verification/order` persists checks and returns status (`Passed` / `Failed`) and overall decision (`READY_FOR_APPROVAL` / `BLOCKED`).

### Phase 8 – Customer Approval and Verified Order Management: COMPLETED
- **Order Lifecycle Management:** Orders progress through strict states: `pending_verification` -> `verified` -> `approved` -> `paypal_pending` -> `completed` / `rejected`.
- **Snapshot Immutability:** Orders freeze cart items, totals, intent requirements, and calculate a deterministic SHA-256 snapshot hash.
- **Alembic Migration:** `0004_create_orders_and_approvals` creates `orders` and `approvals` tables.
- **Customer Approval Invariants:** `POST /api/approvals/{order_id}/approve` strictly enforces that the order is `verified`, cart items have not mutated, and order version matches.

### Phase 9 – PayPal Sandbox Payment Integration: COMPLETED
- **REST API v2 Checkout:** Integrated genuine server-to-server communication with PayPal Sandbox (`https://api-m.sandbox.paypal.com`).
- **OAuth 2.0 Token Caching:** In-memory token cache with TTL expiration and automatic background refresh.
- **Payment Creation Preconditions:** `POST /api/payments/create-order` strictly requires `approved` order status and server-calculated amount (never client-supplied).
- **Payment Capture & Fulfillment:** `POST /api/payments/capture-order` captures authorized transactions, prevents duplicate captures (409 Conflict), transitions order to `completed`, records verified transaction, and clears the cart.

### Phase 10 – Transaction Management & Tamper-Evident Audit System: COMPLETED
- **PostgreSQL Models & Migration:** `Transaction` and `AuditEvent` models created via Alembic revision `0005_create_transactions_and_audit`.
- **Append-Only SHA-256 Hash Chain:** Every security-relevant event produces a cryptographically chained audit record linked to the previous event hash.
- **Cryptographic Integrity Verification:** `POST /api/audit/verify-integrity` walks the user's hash chain using constant-time `hmac.compare_digest` to detect any database tampering.
- **Dashboard Aggregations:** `GET /api/dashboard` provides real-time counts of requests, verified orders, blocked transactions, recent orders, and security activity.

### Phase 11 – Complete System Integration, Security Hardening & Verification: COMPLETED
- **Comprehensive E2E Integration Suite:** `backend/tests/test_e2e_workflow.py` validates the complete 11-stage purchase flow and negative adversarial vectors.
- **100% Test Pass Rate:** 150 automated tests pass with zero regressions.
- **Bounded In-Memory Caching:** SHA-256 canonical payload hashing with LRU eviction and configurable TTL (`SECURITY_SCAN_CACHE_TTL_SECONDS=300`).

---

## 3. Product Provider & Platform Status

| Provider | ID | Type | Status | Support / Availability |
| :--- | :--- | :--- | :--- | :--- |
| **DummyJSON** | `dummyjson` | Demo Catalogue | `ACTIVE` | Supported (Real HTTP integration, live sample catalogue) |
| **Amazon** | `Amazon` | Marketplace | `NOT_CONFIGURED` | Unsupported (Prototype does not connect to live API) |
| **Flipkart** | `Flipkart` | Marketplace | `NOT_CONFIGURED` | Unsupported (Prototype does not connect to live API) |
| **Myntra** | `Myntra` | Marketplace | `NOT_CONFIGURED` | Unsupported (Prototype does not connect to live API) |

> [!NOTE]
> DummyJSON is a demonstration product source. It provides sample catalogue data for prototype testing and does not represent verified real-world sellers or live merchant inventory.

---

## 4. Python Environment Setup (Windows PowerShell)

The committed `.venv` directory inside `backend/` references a developer's machine path and should not be activated. A dedicated external virtual environment is used:

```powershell
# 1. Create external virtual environment using Python 3.14
py -3.14 -m venv "$env:LOCALAPPDATA\TrustPayAI\backend-venv"

# 2. Upgrade pip
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m pip install --upgrade pip

# 3. Install backend dependencies
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m pip install -r backend\requirements.txt

# 4. Verify dependency integrity
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m pip check
```

---

## 5. Configuration and Environment Setup

### Step 1: Create Local Environment File
Copy the example file to `.env` in the `backend/` directory:
```powershell
Copy-Item backend\.env.example backend\.env
```

### Step 2: Configure Environment Variables
Configure your database, product provider, and Gemini AI settings in `backend/.env`:
```env
# Database Settings
DATABASE_URL=postgresql+psycopg://YOUR_USER:YOUR_PASSWORD@localhost:5432/trustpay_ai

# Security & JWT
JWT_SECRET_KEY=your-secure-random-secret-key-at-least-32-characters
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Product Provider & Caching Settings (Phase 3)
DUMMYJSON_BASE_URL=https://dummyjson.com
DUMMYJSON_ENABLED=true
PRODUCT_REQUEST_TIMEOUT_SECONDS=10.0
PRODUCT_CACHE_TTL_SECONDS=300
PRODUCT_CATEGORY_CACHE_TTL_SECONDS=1800
PRODUCT_CACHE_MAX_ENTRIES=500
PRODUCT_MAX_PAGE_SIZE=200
PRODUCT_RETRY_ATTEMPTS=2

# Google Gemini AI & Intent Extraction (Phase 4)
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=30.0
GEMINI_MAX_RETRIES=1
GEMINI_MAX_CONCURRENT_REQUESTS=5
INTENT_MAX_REQUEST_CHARS=4000
INTENT_MAX_OUTPUT_TOKENS=2000

# Prompt Injection & Content Security (Phase 5)
SECURITY_SCAN_MAX_CONTENT_CHARS=20000
SECURITY_SCAN_MAX_FIELDS=20
SECURITY_SCAN_MAX_FINDINGS=50
SECURITY_SCAN_MAX_GEMINI_OUTPUT_TOKENS=1500
SECURITY_SCAN_MAX_CONCURRENT_AI_REQUESTS=3
SECURITY_SCAN_CACHE_TTL_SECONDS=300
SECURITY_SCAN_CACHE_MAX_ENTRIES=500
```

> [!IMPORTANT]
> When `GEMINI_API_KEY` is not configured, the backend returns HTTP 503 `AI_NOT_CONFIGURED` with a clear explanation, rather than fabricating fake AI extractions.

---

## 6. Database Migrations (Alembic)

Run migrations from the repository root:
```powershell
# View migration history
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m alembic -c backend\alembic.ini history

# Apply migrations to head (creates users and auth_sessions tables)
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m alembic -c backend\alembic.ini upgrade head

# Check current revision
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m alembic -c backend\alembic.ini current
```

---

## 7. Running the Server

Start FastAPI with Uvicorn:
```powershell
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

### Key API Endpoints

#### Health & Diagnostics
- **Application Liveness:** `GET http://127.0.0.1:8000/health`
- **PostgreSQL Readiness:** `GET http://127.0.0.1:8000/api/health`

#### Authentication & User Management (Phase 2)
- **Register:** `POST http://127.0.0.1:8000/api/auth/register` (Returns 201 Created + JWT token + user profile)
- **Login:** `POST http://127.0.0.1:8000/api/auth/login` (Returns 200 OK + JWT token + user profile)
- **Current User Profile:** `GET http://127.0.0.1:8000/api/auth/me` (Bearer token required)
- **Profile Alias:** `GET http://127.0.0.1:8000/api/users/profile` (Bearer token required)
- **Logout:** `POST http://127.0.0.1:8000/api/auth/logout` (Bearer token required; immediately revokes session)

#### Product Catalogue & Platforms (Phase 3)
- **Supported Platforms:** `GET http://127.0.0.1:8000/api/platforms`
- **Product Listing:** `GET http://127.0.0.1:8000/api/products?limit=20&skip=0`
- **Category Filter:** `GET http://127.0.0.1:8000/api/products?category=smartphones&limit=20`
- **Keyword Search:** `GET http://127.0.0.1:8000/api/products/search?q=laptop&limit=20`
- **Product Categories:** `GET http://127.0.0.1:8000/api/products/categories`
- **Product Details:** `GET http://127.0.0.1:8000/api/products/{product_id}`
- **Intent Recommendations:** `POST http://127.0.0.1:8000/api/recommendations/search` (and `GET /api/recommendations/search`)

#### Gemini AI Intent Extraction (Phase 4)
- **Natural-Language Policy Extraction:** `POST http://127.0.0.1:8000/api/intent/parse` (Bearer token required)
  ```json
  {
    "request": "I need a gaming laptop under $1200 with 16GB RAM, 512GB SSD, Intel i7 processor, preferably ASUS. Do not show refurbished.",
    "maximumBudget": 1200.0,
    "currency": "USD",
    "category": "laptops",
    "trustedSellersOnly": true,
    "platformId": "dummyjson"
  }
  ```

#### Prompt Injection & Content Security (Phase 5)
- **Product Content Security Scan:** `POST http://127.0.0.1:8000/api/security/analyze-product` (Bearer token required)
  ```json
  {
    "product_id": 1,
    "provider": "DEMO",
    "analysis_mode": "HYBRID"
  }
  ```
  Returns `ProductSecurityScanResponse` with `risk_level`, `analysis_status`, `detected`, `findings`, `content_hash`, and summary.

---

## 8. PowerShell Testing Commands

You can test the running API directly using Windows PowerShell:

```powershell
# 1. Check application liveness
Invoke-RestMethod -Uri "http://localhost:8000/health"

# 2. Check shopping platforms
Invoke-RestMethod -Uri "http://localhost:8000/api/platforms"

# 3. Retrieve product catalog with pagination
Invoke-RestMethod -Uri "http://localhost:8000/api/products?limit=10&skip=0"

# 4. Filter products by category
Invoke-RestMethod -Uri "http://localhost:8000/api/products?category=beauty&limit=5"

# 5. Search products by keyword
Invoke-RestMethod -Uri "http://localhost:8000/api/products/search?q=laptop"

# 6. Retrieve product categories
Invoke-RestMethod -Uri "http://localhost:8000/api/products/categories"

# 7. Extract shopping policy from customer text (requires Bearer token)
$headers = @{ Authorization = "Bearer YOUR_JWT_TOKEN" }
$body = @{
    request = "I need a laptop with at least 16GB RAM and 512GB SSD under $900"
    maximumBudget = 900.0
    currency = "USD"
    category = "laptops"
    trustedSellersOnly = $true
    platformId = "dummyjson"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/intent/parse" -Headers $headers -ContentType "application/json" -Body $body

# 8. Analyze product metadata for prompt injection (requires Bearer token)
$secBody = @{
    product_id = 1
    provider = "DEMO"
    analysis_mode = "HYBRID"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/security/analyze-product" -Headers $headers -ContentType "application/json" -Body $secBody
```

---

## 9. Running Automated Tests

Run the full asynchronous test suite (150 tests across all 11 phases):
```powershell
& "$env:LOCALAPPDATA\TrustPayAI\backend-venv\Scripts\python.exe" -m pytest backend/tests -v
```

---

## 10. Troubleshooting

1. **`No Python at '...'` error:**
   Do not activate `backend\.venv`. Use the external environment at `"$env:LOCALAPPDATA\TrustPayAI\backend-venv"`.
2. **`AI_NOT_CONFIGURED` on `/api/intent/parse`:**
   Add a valid `GEMINI_API_KEY` to `backend/.env`. Get an API key from Google AI Studio (https://aistudio.google.com).
3. **PostgreSQL Connection Refused:**
   Ensure the `postgresql-x64-16` Windows service is running via PowerShell:
   `Get-Service -Name *postgres*`
4. **Token Revocation in PostgreSQL:**
   When a user logs out, the JWT session identifier (`jti`) is marked inactive in PostgreSQL. Subsequent requests are rejected with HTTP 401 Unauthorized.
