# TrustPay AI API integration contract

This document distinguishes the API surface implemented by the local prototype from the marketplace/FastAPI contract the team still needs to agree and implement. It is not evidence that pending routes or providers are live.

## Client configuration and authentication

- Configure only `VITE_API_BASE_URL` in `frontend/.env`, for example `http://localhost:8000`.
- `src/services/api.ts` creates the shared Axios client, appends `/api`, applies a 10-second timeout, and attaches the application JWT as `Authorization: Bearer <token>`.
- Never put Amazon, Flipkart, Myntra, Gemini, or PayPal secrets in Vite environment variables or browser storage.
- Current backend errors generally use FastAPI's `{ "detail": "..." }` shape. The frontend displays that detail and does not replace failed calls with successful mock responses.

## Implemented local backend routes

| Frontend operation | Current local method/path | Request / response notes |
|---|---|---|
| Register | `POST /api/auth/register` | `{name,email,password}` → `{access_token,token_type,user}` |
| Login | `POST /api/auth/login` | `{email,password}` → `{access_token,token_type,user}` |
| Current user | `GET /api/auth/me` | Bearer JWT → user |
| Platform list | `GET /api/platforms` | Legacy platform list; DummyJSON is supported, marketplace stores are not |
| Product list/search | `GET /api/products?q=&category=&limit=` | Returns DummyJSON `{products,total,skip,limit}` |
| Product categories | `GET /api/products/categories` | DummyJSON category array |
| Product details | `GET /api/products/{product_id}` | Numeric DummyJSON product ID |
| Marketplace provider status | `GET /api/products/providers` | Probes DummyJSON; external providers are never reported connected without tested adapters |
| Normalized marketplace search | `GET /api/products/search?q=&provider=&category=&limit=` | Returns normalized DummyJSON data for `DEMO`; other marketplace requests return HTTP 503 until an authorized adapter is implemented |
| Recommendations | `POST /api/recommendations/search` | `{intent}` → `{recommendations:[{product,analysis}],total}` |
| Intent parse | `POST /api/intent/parse` | `{request,maximumBudget,currency,category,trustedSellersOnly,platformId}` → parsed purchase policy |
| Cart read | `GET /api/cart` | `{items:[{product,quantity}],totals}` |
| Cart add/update/remove | `POST /api/cart/items`, `PUT /api/cart/items/{product_id}`, `DELETE /api/cart/items/{product_id}` | Legacy cart uses numeric DummyJSON IDs |
| Clear cart | `DELETE /api/cart/items` | The current route differs from the proposed `DELETE /api/cart` |
| Order | `POST /api/orders` | `{intent}` → versioned order and backend-calculated totals |
| Verify order | `POST /api/verification/order` | `{order_id}` → backend checks and totals |
| Approve order | `POST /api/approvals/{order_id}/approve` | `{order_version}` |
| PayPal Sandbox | `POST /api/payments/create-order`, `POST /api/payments/capture-order` | Backend-only PayPal credentials; capture result is provider-confirmed |
| Transactions | `GET /api/transactions` | Transaction array; no transaction detail route yet |
| Audit | `GET /api/audit`, `POST /api/audit/verify-integrity` | Current integrity route uses POST |
| Health | `GET /health` | `{ "status": "ok" }` |

These are the existing local backend contracts. The frontend service layer currently adapts them; do not silently rename paths in the UI when merging another backend.

## Marketplace endpoints and current availability

The local backend implements both marketplace routes. `src/services/marketplaceService.ts` validates the response contract. The DummyJSON connection is probed against the public API when provider status is requested. Amazon, Flipkart, and Myntra are not connected; their status is `NOT_CONFIGURED` unless credentials are present without an adapter (then `TEMPORARILY_UNAVAILABLE`), and selected-provider searches return an explicit HTTP 503 rather than DummyJSON products.

### Provider status

`GET /api/products/providers` (Bearer JWT)

```json
{
  "providers": [
    { "name": "AMAZON", "connected": false, "status": "NOT_CONFIGURED" },
    { "name": "FLIPKART", "connected": false, "status": "NOT_CONFIGURED" },
    { "name": "MYNTRA", "connected": false, "status": "NOT_CONFIGURED" },
    { "name": "DEMO", "connected": true, "status": "CONNECTED" }
  ]
}
```

Allowed `status` values: `CONNECTED`, `NOT_CONFIGURED`, `TEMPORARILY_UNAVAILABLE`, `AUTHENTICATION_FAILED`. The `connected` flag must be based on the provider's actual backend configuration/health, not on the visibility of a UI filter. Optional `message` can provide a user-safe explanation; never return secrets.

### Product search and details

The Amazon response below is a schema illustration, not a live result. The implemented backend currently returns DummyJSON data only for `provider=DEMO`; requests for AMAZON, FLIPKART, or MYNTRA return HTTP 503. Demo responses also include `provider: "DEMO"` and `source: "DummyJSON"`.

`GET /api/products/search?q=laptop&provider=AMAZON` (Bearer JWT; provider is optional for all connected providers).

```json
{
  "products": [
    {
      "id": "trustpay-product-id",
      "external_product_id": "provider-item-id",
      "provider": "AMAZON",
      "title": "Product title from provider",
      "description": null,
      "image_url": null,
      "price": null,
      "currency": "INR",
      "category": null,
      "rating": null,
      "product_url": null,
      "seller_name": null,
      "seller_verified": null,
      "specifications": {},
      "source_updated_at": null
    }
  ],
  "total": 1
}
```

Every attribute may be missing/null if the provider does not supply it; do not infer seller verification, specifications, prices, or currency. Search may return an empty `products` array. Demo products are explicitly labeled `DEMO` and use USD as returned by DummyJSON. Seller details are not invented.

Recommended details route: `GET /api/products/{product_id}?provider=AMAZON` (Bearer JWT) returning one product in the same schema. The current local details route only accepts a numeric DummyJSON product ID.

### Cart requirements for marketplace products

The local cart currently accepts numeric DummyJSON IDs only. Before enabling Add to Cart for Amazon/Flipkart/Myntra results, implement a provider-aware cart contract, for example:

`POST /api/cart/items`

```json
{ "product_id": "trustpay-product-id", "provider": "AMAZON", "quantity": 1 }
```

The backend must re-fetch/validate the product and calculate authoritative price/totals; frontend-submitted prices must not be trusted. Update, remove, and order/verification snapshots must preserve the provider plus external product ID. Until that is available, the UI disables cart progression for non-demo listings.

## Proposed shopping/verification contract (not implemented by the local backend)

| Requested operation | Proposed method/path | Example request |
|---|---|---|
| Parse request | `POST /api/shopping/parse` | `{ "request": "Laptop below INR 60000", "currency": "INR" }` |
| Create saved request | `POST /api/shopping/requests` | `{ "request": "...", "requirements": {...}, "budget": 60000, "currency": "INR" }` |
| Run verification | `POST /api/verification/check` | `{ "cart_id": "...", "shopping_request_id": "..." }` |
| Create approval | `POST /api/approval/create` | `{ "order_id": "...", "verification_id": "..." }` |
| Confirm approval | `POST /api/approval/{approval_id}/confirm` | `{ "order_version": 1, "confirmed": true }` |
| Read transaction detail | `GET /api/transactions/{transaction_id}` | No request body |
| Audit logs | `GET /api/audit/logs` | No request body |
| Audit integrity | `GET /api/audit/verify-integrity` | No request body |

The current local backend instead implements `/intent/parse`, `/verification/order`, `/approvals/{order_id}/approve`, `GET /audit`, and `POST /audit/verify-integrity`. Confirm the final contract with the backend owner, then update the relevant typed service in one place. Example success payloads for these proposed routes should be finalized by the backend owner; do not fabricate them in the frontend.

Intent parsing uses deterministic extraction when `GEMINI_API_KEY` is absent. Gemini may optionally extract policy fields when configured on the backend; the frontend never receives or stores the key. Verification remains deterministic and backend-authoritative. The prompt-injection check is a limited rule-based demonstration against untrusted product descriptions, not a complete security scanner.

## Provider access and backend configuration

- Amazon Product Advertising API 5 is deprecated; use Amazon's supported Creators API for eligible Associates accounts, following Amazon's current terms and onboarding.
- Use Flipkart's Affiliate Product API only with approved affiliate access and credentials.
- Do not scrape storefront pages. Do not invent a Myntra API; enable Myntra only after its official partner/catalogue access is confirmed.
- Backend provider secrets belong in the teammate's backend `.env` or secret manager. Return only safe status/errors to the frontend.
- The UI currently supports filtering by provider status, shared product display, product comparison, and provider search contract. It does not claim that Amazon, Flipkart, or Myntra is connected.

## Error behavior

Use normal HTTP statuses and a safe FastAPI error body:

```json
{ "detail": "Amazon catalogue access is not configured." }
```

Use `401` for missing/expired authentication, `403` for access denied, `404` for unknown resources, `422` for invalid input, `502`/`503` for provider failures or unconfigured services. Do not return credentials, request signatures, provider tokens, or raw provider stack traces.
