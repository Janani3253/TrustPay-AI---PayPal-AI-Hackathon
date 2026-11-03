# TrustPay AI — IntentLock

TrustPay AI frontend for customer-intent verification. The React app connects to the FastAPI service in the repository's `backend` folder. Customers sign in, select a shopping platform, and then browse products from that platform. Only DummyJSON Demo Store is connected; Amazon, Flipkart, and Myntra are clearly marked unsupported.

## Run locally

Start the backend first by following [`../backend/README.md`](../backend/README.md), then start the frontend:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend\.env`. The centralized Axios client uses `/api` endpoints on that backend and attaches the backend-issued bearer token.

Production checks:

```sh
npm run build
npm run lint
```

## Product API configuration

The backend proxies the configurable product source, defaulting to `https://dummyjson.com`. Set `DUMMYJSON_BASE_URL` in `backend\.env` to change it. The API client and typed mapping are isolated in `src/services/api.ts`, `src/services/backendService.ts`, and `src/services/productService.ts`.

Products, descriptions, categories, ratings, images, brand/SKU/weight/dimensions when present, and prices come from DummyJSON. Prices are displayed in USD, the currency supplied by this API. No INR conversion is fabricated. A request using another currency cannot be reliably compared against API prices and will not pass the budget check. DummyJSON does not provide verified-seller information or many technical specifications, which are marked unavailable rather than inferred. API failures are shown explicitly; catalogue mock products are not substituted.

## Frontend workflow

1. Register or sign in; the backend issues a JWT.
2. Select a shopping platform from the dashboard. Only DummyJSON Demo Store is selectable.
3. Enter a shopping request and review the policy returned by the backend.
4. Search recommendations and review backend-returned product status.
5. Add products to the server-persisted cart and review the server-calculated estimated fees.
6. Run backend IntentLock checks; failed critical checks block approval.
7. Approve the exact backend order version.
8. If configured, continue to PayPal Sandbox and let the backend create/capture the provider order.
9. Review backend transaction history and audit-chain integrity.

## Demo limitations

- Authentication, intent extraction, cart, order verification, approval, transactions, and audit records use the FastAPI backend.
- PayPal is a real provider Sandbox flow only when backend credentials are configured. Without them, the backend returns a configuration error; no fake successful payment is generated.
- Seller identity and technical product specifications are not verified by the public catalogue API.
- Passwords are PBKDF2-hashed and user/cart/order/transaction/audit data are stored in the local SQLite database. This local prototype is not a production identity or payment system.
- Seller identity and technical product specifications are not supplied by DummyJSON and remain unverified.
- Replace `TRUSTPAY_SECRET_KEY` and configure CORS and PayPal Sandbox credentials before sharing the backend beyond local development.

## Structure

- `src/pages/Pages.tsx` — landing, authentication, catalogue, request, checkout, transaction, and audit screens.
- `src/components/` — reusable app navigation, branding, and dashboard components.
- `src/context/AppContext.tsx` — shared authentication and shopping workflow state.
- `src/services/` — typed API access and product mapping.
- `src/types/` — shared API and application data types.
- `src/utils/` — order snapshot utilities.
- `../backend/app/` — FastAPI endpoints, SQLite persistence, JWT auth, order checks, and PayPal Sandbox integration.


# Terminal 2 — frontend
Set-Location frontend
npm run dev