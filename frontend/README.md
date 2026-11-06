# TrustPay AI — IntentLock

Responsive React/Vite frontend for the TrustPay AI customer-intent shopping and payment workflow. It uses the existing FastAPI service, keeps provider calls in typed services, and does not place marketplace or payment secrets in the browser.

## Run locally

Start the backend using the instructions in [`../backend/README.md`](../backend/README.md). In a second PowerShell terminal:

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm install
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend\.env`. The shared Axios client appends `/api`, applies a timeout, and attaches the signed-in user's JWT. Do not put provider credentials in this file.

## Current integrations

- Login, registration, session restoration/logout, shopping intent, DummyJSON product search, recommendations, backend-authoritative cart totals, order verification, approval, PayPal Sandbox, transactions, and audit records use the existing FastAPI endpoints.
- Product and category requests use the canonical `platform=dummyjson` query parameter and honor backend pagination.
- DummyJSON is the only supported shopping platform. Amazon, Flipkart, and Myntra are unavailable; the frontend does not show them as connected or substitute Demo products for their unavailable catalogues.
- Verification and approval are session-only frontend state backed by server checks; a refresh clears those indicators and requires verification and approval again.
- PayPal Sandbox is available only when backend credentials exist; successful payment is shown only after backend-confirmed capture.

See [`API_INTEGRATION.md`](./API_INTEGRATION.md) for the routes, payloads, and response shapes used by the frontend.

## Quality checks

```powershell
npm run lint
npm run build
```

## Project layout

- `src/pages/` — landing, auth, dashboard, product, request, order, verification, payment, transaction, and audit pages.
- `src/context/` — authentication and shared shopping state.
- `src/services/` — Axios client and typed API adapters.
- `src/types/` — API and application data types.
