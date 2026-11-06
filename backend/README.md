# TrustPay AI FastAPI backend

This backend connects the frontend to a persistent local SQLite store, DummyJSON product data, and optional PayPal Sandbox APIs. Only the DummyJSON Demo Store is supported for product browsing. Other listed stores are explicitly marked unsupported.

## Run locally (Windows PowerShell)

### First-time setup

Run these commands from the repository root. Create the virtual environment outside the repository so it
does not reuse a checked-in environment tied to another machine or Python installation. Python 3.11 or newer
is recommended.

```powershell
$venv = Join-Path $env:LOCALAPPDATA 'venvs\trustpay-ai'
if (-not (Test-Path "$venv\Scripts\python.exe")) { python -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
& "$venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Keep the backend terminal open. In a second PowerShell terminal from the repository root, start the frontend:

```powershell
Set-Location frontend
if (-not (Test-Path node_modules)) { npm ci }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run dev -- --host 127.0.0.1
```

For later runs, use the same commands to start each server. Do not activate or repair an existing `backend\.venv`
if it points to an unavailable Python executable; create a fresh environment at the path above instead.

Confirm the backend is responding with `Invoke-RestMethod http://127.0.0.1:8000/health`.
The health check is also available at `http://localhost:8000/health`; interactive API documentation is at
`http://localhost:8000/docs`. The browser app calls `http://localhost:8000/api` by default.

## Configuration

Configure backend values in `backend\.env`. Do not put PayPal secrets in the frontend or commit `backend\.env`.

- `TRUSTPAY_SECRET_KEY` — replace the development value with a long random secret.
- `TRUSTPAY_DATABASE_PATH` — SQLite file path; defaults to `backend\trustpay.db`.
- `TRUSTPAY_CORS_ORIGINS` — comma-separated trusted frontend origins.
- `DUMMYJSON_BASE_URL` — public catalogue service base URL.
- `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` — optional PayPal Sandbox credentials. Checkout stays unavailable until these are configured.
- `PAYPAL_API_BASE_URL` — defaults to the PayPal Sandbox API.
- `FRONTEND_BASE_URL` — frontend URL for PayPal return and cancellation.

### PayPal Sandbox checkout

1. In the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/), use the **Sandbox** environment
   and create a Sandbox **Business** account for the seller and a Sandbox **Personal** account for the buyer.
2. Open **Apps & Credentials**, select **Sandbox**, and create an app owned by the seller account. Copy its
   Client ID and Secret into `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in `backend\.env` only.
3. Keep `PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com` and set
   `FRONTEND_BASE_URL=http://localhost:5173`. Restart FastAPI after editing backend configuration.
4. Sign in to the frontend, create an order, pass verification, approve the exact order, and continue to PayPal.
   Complete checkout using the Sandbox buyer account, not a real PayPal account.

The backend creates the PayPal order from the verified server-side order snapshot, validates the returned
amount, currency, reference and capture before recording a transaction, and reuses deterministic request IDs
for safe retries. Return and cancellation callbacks are reconciled with PayPal before the UI reports an outcome.
If the payment result is temporarily unavailable, use **Check payment status** rather than starting a second
checkout. A changed cart is preserved after a completed payment.

Do not share or commit Sandbox credentials, tokens, or real buyer information. The API base URL and approval
redirect are restricted to PayPal Sandbox hosts.

### Payment API endpoints

All payment endpoints require the normal TrustPay bearer token:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/payments/create-order` | Create or resume the PayPal Sandbox order for an approved TrustPay order. |
| `POST` | `/api/payments/capture-order` | Capture or reconcile a PayPal order returned by PayPal. |
| `POST` | `/api/payments/cancel-order` | Reconcile a TrustPay order after the buyer cancels checkout. |
| `GET` | `/api/transactions` | List completed transactions for the signed-in user. |

### Troubleshooting

- **`No Python at ...`**: the active virtual environment references a Python installation from another machine
  or user. Do not activate that environment; create the external environment shown above.
- **`vite` is not recognized**: run `npm ci` from `frontend` and then start Vite from that directory.
- **PayPal checkout is unavailable**: confirm both backend-only credentials are set in `backend\.env`, then
  restart FastAPI. Never put the secret in a frontend `.env` file.
- **PayPal could not be reached or rejected credentials**: verify network access and that the app credentials
  belong to the Sandbox seller account. No real-money payment is supported.
- **Payment status is pending or reconciliation is required**: retry **Check payment status** on the return page.
  The backend confirms provider state before recording a transaction; do not treat a browser redirect alone as
  proof of payment.

Amazon, Flipkart, Myntra, and other marketplaces are not connected in this prototype. Do not enter marketplace
credentials in the frontend or enable a platform until an approved official API, its access terms, and the required
backend-only credentials are configured. Never use storefront scraping as a substitute for authorized product APIs.

## Implemented API

The backend implements JWT register/login/current-user endpoints, supported platform discovery, natural-language policy extraction, product listing/categories/details, recommendation analysis, per-user cart persistence, versioned orders, server-side IntentLock checks and approval, optional PayPal Sandbox create/capture, transactions, dashboard counters, and a SHA-256 linked audit log with integrity verification.

Verification deliberately reports specifications as needing review and seller status as unverified when the product catalogue does not provide those facts. The demonstration uses SQLite and estimated shipping/tax rates; it is not production-ready financial infrastructure.


## Automated checks

The backend payment tests use a temporary SQLite database and mocked PayPal responses; they do not need Sandbox
credentials:

```powershell
Set-Location backend
& (Join-Path $env:LOCALAPPDATA 'venvs\trustpay-ai\Scripts\python.exe') -m unittest discover -s tests -v
```

Build the frontend from its directory with `npm run build`.