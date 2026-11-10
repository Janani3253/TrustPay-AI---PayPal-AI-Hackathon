# Frontend API integration

The frontend uses the local FastAPI backend as the source of truth for authentication, product data, cart totals, orders, verification, approvals, and payment. The shared Axios client appends `/api` to `VITE_API_BASE_URL`, attaches the saved bearer token, and applies a request timeout.

## Authentication

| Method and route | Request / response |
|---|---|
| `POST /api/auth/register` | `{name,email,password}` → `{access_token,token_type,user}` |
| `POST /api/auth/login` | `{email,password}` → `{access_token,token_type,user}` |
| `GET /api/auth/me` | Restores the authenticated user session |
| `POST /api/auth/logout` | Revokes the backend session; the frontend also clears the local token on failure |

Protected requests require the bearer token. A `401` while restoring `/api/auth/me` clears the local session; backend error details (including validation messages) are shown to the user.

## Platforms and products

`GET /api/platforms` is optional-auth and provides platform availability. DummyJSON (`dummyjson`) is the only supported shopping platform. The UI will not select an unsupported platform, route a request or recommendation to one, or show DummyJSON items as a substitute for an unavailable marketplace.

All product operations specify the backend query parameter `platform=dummyjson`:

| Method and route | Request / response |
|---|---|
| `GET /api/products/categories?platform=` | Category array |
| `GET /api/products/search?q=&limit=&skip=&platform=` | `{products,total,skip,limit}` |
| `GET /api/products?q=&category=&limit=&skip=&platform=` | `{products,total,skip,limit}` |
| `GET /api/products/{id}?platform=` | One normalized product |

Search uses `/products/search` when a non-empty query is supplied without a category; combined query/category filters use `/products`. Product pages follow the response pagination envelope. Only numeric Demo product IDs are accepted by the cart.

## Intent, recommendations, cart, and checkout

| Method and route | Request / response |
|---|---|
| `POST /api/intent/parse` | `{request,maximumBudget,currency?,category?,trustedSellersOnly?,platformId?}`; the frontend sends canonical `platformId: "dummyjson"` |
| `POST /api/recommendations/search` | `{intent}` → `{recommendations:[{product,analysis}],total}` |
| `GET /api/cart` | Backend-authoritative `{items,totals}` |
| `POST /api/cart/items` | `{product_id,quantity?}` |
| `PUT /api/cart/items/{id}` | `{quantity}` |
| `DELETE /api/cart/items/{id}` or `DELETE /api/cart/items` | `204` |
| `POST /api/orders` | `{intent}` → versioned order snapshot and backend totals |
| `GET /api/orders/{id}` | Retrieves an authenticated user's order |
| `POST /api/verification/order` | `{order_id}` → server verification |
| `POST /api/approvals/{id}/approve` | `{order_version}` |
| `POST /api/payments/create-order` | `{order_id}` → backend-created PayPal Sandbox checkout |
| `POST /api/payments/capture-order` | `{paypal_order_id}` → provider-confirmed capture result |

Cart product IDs, quantities, and totals come from the backend. The frontend does not persist the cart, order, verification, or approval snapshots as proof of state. Refreshing clears the in-memory verification/approval state; users must re-run backend verification and approval before checkout.

Gemini or other missing backend configuration can cause `503`. Validation errors (`422`), expired sessions (`401`), and stale order snapshots (`409`) are displayed rather than replaced with mock success.

## Account activity

Dashboard, transactions, and audit operations are protected backend calls. The frontend uses `GET /api/dashboard`, `GET /api/transactions`, `GET /api/audit`, and `POST /api/audit/verify-integrity`. No local audit records are presented as backend audit events.

Amazon, Flipkart, and Myntra integrations are unavailable. No provider search/status endpoint or provider-aware cart is assumed by this frontend.
