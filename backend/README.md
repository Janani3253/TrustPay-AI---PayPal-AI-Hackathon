# TrustPay AI FastAPI backend

This backend connects the frontend to a persistent local SQLite store, DummyJSON product data, and optional PayPal Sandbox APIs. Only the DummyJSON Demo Store is supported for product browsing. Other listed stores are explicitly marked unsupported.

## Run locally (Windows PowerShell)

### First-time setup

Run these commands from the repository root. If PowerShell blocks activation, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

```powershell
py -3.12 -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Keep that terminal open while using the app. In another PowerShell terminal, start the frontend:

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm install
npm run dev
```

For later runs, open two terminals from the repository root. In the first, activate the existing virtual environment and start FastAPI:

```powershell
.\backend\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In the second terminal, start Vite:

```powershell
Set-Location frontend
npm run dev
```

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

Amazon, Flipkart, Myntra, and other marketplaces are not connected in this prototype. Do not enter marketplace
credentials in the frontend or enable a platform until an approved official API, its access terms, and the required
backend-only credentials are configured. Never use storefront scraping as a substitute for authorized product APIs.

## Implemented API

The backend implements JWT register/login/current-user endpoints, supported platform discovery, natural-language policy extraction, product listing/categories/details, recommendation analysis, per-user cart persistence, versioned orders, server-side IntentLock checks and approval, optional PayPal Sandbox create/capture, transactions, dashboard counters, and a SHA-256 linked audit log with integrity verification.

Verification deliberately reports specifications as needing review and seller status as unverified when the product catalogue does not provide those facts. The demonstration uses SQLite and estimated shipping/tax rates; it is not production-ready financial infrastructure.


## Run backend
# Terminal 1 — backend
.\backend\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000