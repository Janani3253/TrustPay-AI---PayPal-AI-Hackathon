# TrustPay AI — Frontend and Backend Status

**Status checked:** 3 November 2026  
**Project:** TrustPay AI — IntentLock customer-intent shopping and payment demo

This document records what is implemented in this workspace, how catalogue products reach the UI, which API calls were tested, and what remains pending. It distinguishes real API data from demo estimates and integrations that are not configured.

## Executive summary

- The React/Vite frontend and FastAPI backend are running locally.
- **Product data is currently fetched from the real DummyJSON public products API through the FastAPI backend.** It is not a hardcoded product list.
- Search works through the current backend's `GET /api/products?q=...` endpoint.
- DummyJSON is a demo catalogue, not Amazon, Flipkart, or Myntra.
- Amazon India, Flipkart India, and Myntra are **not connected**. The backend now implements provider status and normalized search routes, but those external adapters remain unavailable.
- The frontend shows provider connectivity as unavailable/unknown when the backend cannot report status. It does not display fabricated marketplace results.
- Payment is a PayPal Sandbox integration path on the backend, but checkout cannot be completed unless Sandbox credentials are configured server-side.

## What is implemented

### Frontend

Implemented screens and workflow:

1. Landing page and account entry points.
2. Registration and login through backend JWT endpoints.
3. Dashboard with backend account metrics and activity.
4. Required shopping-platform selection.
5. Product catalogue with search, category, price, rating, and sort controls.
6. Marketplace provider status filters for Amazon, Flipkart, Myntra, and the Demo Store.
7. Common marketplace product display model and comparison of up to three products.
8. Natural-language shopping request and returned purchase policy.
9. Product recommendation results from the backend.
10. Server-persisted cart and order summary.
11. Backend IntentLock checks and exact-order approval.
12. PayPal Sandbox checkout interface.
13. Transaction history and backend audit log/integrity display.
14. Responsive layout and success/error/info action notifications.

Marketplace-specific Add to Cart is intentionally unavailable for non-demo listings until the backend supports provider-aware product IDs and authoritative provider pricing. The existing DummyJSON cart remains functional.

### Backend

The local FastAPI backend currently provides:

- JWT registration, login, and current-user routes.
- Supported-platform discovery.
- Deterministic intent parsing with optional, backend-only Gemini extraction when configured.
- DummyJSON product listing, query search, categories, and details.
- Backend recommendations, per-user cart persistence, order snapshots, verification, and approval.
- Optional PayPal Sandbox order creation/capture.
- Dashboard, transactions, and a SHA-256-linked audit log with integrity verification.

The local database is SQLite. PostgreSQL and completed external marketplace provider services described in the project plan are not implemented in this local prototype.

## How products appear in the frontend

1. The signed-in customer chooses **DummyJSON Demo Store** from the platform picker.
2. The frontend calls the FastAPI API using its shared Axios client at `http://localhost:8000/api`.
3. The backend calls the configured public product source, defaulting to `https://dummyjson.com`.
4. The backend returns product fields including title, description, image, category, rating, and price.
5. The frontend renders those returned fields and labels them as **DummyJSON / Demo Product API** data.

The product catalogue is not sourced from the frontend mock data. DummyJSON prices are USD; the app does not silently convert them to INR. DummyJSON does not establish marketplace seller identity or verified technical specifications, so missing facts are shown as unavailable or unverified.

### Product API status: tested and working

The existing authenticated DummyJSON listing, search, categories, and detail routes were tested earlier. A fresh route-level smoke test used an isolated temporary database and the real DummyJSON service:

| Test | Result |
|---|---|
| `GET /health` | Passed — `{"status":"ok"}` |
| `GET /api/products/providers` | Passed — Demo connected after a successful DummyJSON probe |
| `GET /api/products/search?q=laptop&provider=DEMO` | Passed — normalized DummyJSON results returned |
| `GET /api/products/search?q=laptop&provider=DEMO&category=laptops` | Passed |
| Legacy `GET /api/products?q=laptop&limit=2` | Passed |
| `GET /api/products/search?q=laptop&provider=AMAZON` | Passed — HTTP 503; no Demo substitution |

**Conclusion:** DummyJSON product listing, query search, category filtering, and normalized marketplace responses work. This does not mean Amazon, Flipkart, or Myntra data is available.

The original product list/search contract remains `GET /api/products?q=laptop`. The newer normalized marketplace route is `GET /api/products/search?q=laptop&provider=DEMO`.

## Marketplace provider status

| Provider | Current status | Details |
|---|---|---|
| DummyJSON Demo Store | Connected when the provider-status probe succeeds | Real public DummyJSON API data is proxied through FastAPI |
| Amazon India | Not connected | No Amazon provider integration or credentials configured in this backend |
| Flipkart India | Not connected | No Affiliate Product API provider integration or credentials configured in this backend |
| Myntra India | Not connected | No authorized catalogue/partner API integration has been confirmed |

The frontend consumes these backend routes:

- `GET /api/products/providers` (probes DummyJSON; reports external integrations as unavailable)
- `GET /api/products/search?q=...&provider=...&category=...` (returns normalized DummyJSON results only)

Amazon, Flipkart, and Myntra searches return HTTP 503 until authorized adapters are implemented. The frontend reports the backend-provided status and never uses DummyJSON results as substitutes for those providers.

Marketplace credentials belong only in the backend environment or secret manager. Amazon PA-API 5 is deprecated; use Amazon's current Creators API only with eligible, approved access. Flipkart API use requires approved affiliate access. Do not scrape storefront pages. Do not enable Myntra without confirmed official partner access.

## API routes currently implemented

All `/api/...` endpoints require a bearer token except registration and login.

| Function | Current method and path |
|---|---|
| Register | `POST /api/auth/register` |
| Login | `POST /api/auth/login` |
| Current user | `GET /api/auth/me` |
| Platform list | `GET /api/platforms` |
| Parse intent | `POST /api/intent/parse` |
| Product list and query search | `GET /api/products?q=&category=&limit=` |
| Product categories | `GET /api/products/categories` |
| Product details | `GET /api/products/{product_id}` |
| Marketplace provider status | `GET /api/products/providers` |
| Normalized marketplace search | `GET /api/products/search?q=&provider=&category=&limit=` |
| Recommendations | `POST /api/recommendations/search` |
| Read/add/update/remove cart | `GET /api/cart`, `POST /api/cart/items`, `PUT /api/cart/items/{product_id}`, `DELETE /api/cart/items/{product_id}` |
| Clear cart | `DELETE /api/cart/items` |
| Create order | `POST /api/orders` |
| Verify order | `POST /api/verification/order` |
| Approve order | `POST /api/approvals/{order_id}/approve` |
| PayPal Sandbox | `POST /api/payments/create-order`, `POST /api/payments/capture-order` |
| Dashboard | `GET /api/dashboard` |
| Transactions | `GET /api/transactions` |
| Audit records and integrity | `GET /api/audit`, `POST /api/audit/verify-integrity` |
| Health | `GET /health` |

The detailed request/response notes and contract differences are in [frontend/API_INTEGRATION.md](./frontend/API_INTEGRATION.md).

## Demo behavior and limitations

- Intent extraction uses the deterministic backend fallback without a Gemini key; optional Gemini extraction uses a backend-only key and schema-validates its output. Gemini has not been live-tested here.
- Shipping and tax are backend demo estimates, not provider-confirmed fees.
- DummyJSON product fields are real API data, but its catalog does not verify sellers or provide all technical specifications.
- IntentLock is a local backend demonstration, not a security certification or guarantee.
- Audit hashing makes changes detectable when the chain is checked; it does not make the local SQLite database immutable.
- PayPal Sandbox requires backend-only `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`. Without them, the API reports a configuration error and no successful payment is recorded.
- The database is local SQLite and is not production payment infrastructure.
- Amazon, Flipkart, and Myntra products cannot be added to the legacy cart; the cart currently uses numeric DummyJSON IDs.

## Run locally (Windows PowerShell)

From the project root, start the backend in Terminal 1:

```powershell
.\backend\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Start the frontend in Terminal 2:

```powershell
Set-Location frontend
npm run dev
```

Local URLs:

- Frontend: `http://localhost:5173`
- Backend health: `http://127.0.0.1:8000/health`
- Backend API docs: `http://127.0.0.1:8000/docs`

Use Python 3.12 if creating the backend environment on this machine. Full setup is documented in [backend/README.md](./backend/README.md).

## Validation performed

- `npm run build` — passed.
- `npm run lint` — passed.
- Six backend unit and route tests — passed.
- Live DummyJSON route smoke test, including provider status, normalized search, category search, legacy search, and explicit Amazon-unavailable response — passed.
- Backend health request — passed; backend and frontend listeners were present on ports 8000 and 5173.
- Authenticated product listing, search, categories, and temporary-account cleanup — passed.
- Browser-tested registration, platform selection, DummyJSON product display, product comparison, explicit unavailable marketplace status, and responsive landing-page layout.

## Next steps to complete the broader integration

1. Implement authorized Amazon/Flipkart/Myntra adapters and test them against official APIs.
2. Make cart, order, and verification provider-aware before enabling external-provider Add to Cart; backend prices must remain authoritative.
3. Configure approved provider credentials server-side only.
4. Perform a reviewed, data-preserving PostgreSQL migration if required; the current local database remains SQLite.
5. Configure Gemini if desired and test extraction using authorized credentials.
6. Configure PayPal Sandbox credentials server-side and test provider-approved/captured flows.
