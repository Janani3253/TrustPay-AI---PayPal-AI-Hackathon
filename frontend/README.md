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

- Login, registration, shopping intent, DummyJSON catalogue, recommendations, cart, order verification, approval, PayPal Sandbox, transactions, and audit records call the existing local FastAPI endpoints.
- Product search uses real DummyJSON results through the current backend. Products are labelled as demo catalogue data.
- The catalogue supports provider status display, Amazon/Flipkart/Myntra filters, provider-aware result normalization, and cross-provider product comparison. It does not mark a provider connected without a backend response.
- The local backend implements provider status and normalized search for the DummyJSON Demo Store. Amazon, Flipkart, and Myntra remain unavailable until authorized provider adapters are implemented; adding non-demo products to the legacy cart is disabled.
- Amazon PA-API 5 is deprecated in favor of Amazon Creators API. Flipkart API use requires approved Affiliate access. Myntra must not be enabled without official authorized catalogue/partner access. Keep all provider credentials server-side.
- PayPal Sandbox is available only when backend credentials exist; no successful payment is fabricated.

See [`API_INTEGRATION.md`](./API_INTEGRATION.md) for implemented routes, proposed routes, payloads, response shapes, and backend contract mismatches.

## Quality checks

```powershell
npm run lint
npm run build
```

## Project layout

- `src/pages/` — landing, auth, dashboard, product, request, order, verification, payment, transaction, and audit pages.
- `src/components/marketplace/` — provider status, common marketplace product cards, catalogue, and comparison.
- `src/context/` — authentication and shared shopping state.
- `src/services/` — Axios client and typed API adapters, including marketplace provider normalization.
- `src/types/` — API and application data types.
