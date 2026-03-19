# Super Order Automation

Super Order Automation is a Python 3.11 application for ingesting supplier emails, extracting structured order data from PDF and Excel attachments with Gemini, storing results in Firestore, and reviewing/exporting them through a dashboard UI.

## What the Project Does

- Monitors Gmail for incoming supplier messages.
- Uploads source attachments to Google Cloud Storage.
- Publishes ingestion events through Pub/Sub.
- Runs a processing Cloud Function that classifies suppliers, extracts orders, validates results, and persists them.
- Auto-registers newly discovered barcodes/items when possible.
- Sends response emails with generated Excel outputs.
- Provides a Streamlit dashboard for inbox review, manual upload, supplier management, item management, and order correction.
- Provides a newer parallel Next.js frontend backed by a FastAPI web API.

## Current Architecture

1. Gmail push notifications trigger the `order-bot` Cloud Function.
2. `src/ingestion/ingestor.py` scans unread mail, uploads attachments to GCS, and publishes `OrderIngestedEvent` messages.
3. `process-order-event` downloads the file, runs `src/core/pipeline.py`, writes order documents to Firestore, and generates export files.
4. `renew_watch` is an HTTP Cloud Function intended for Cloud Scheduler to refresh the Gmail watch.
5. The Streamlit dashboard in `src/dashboard/app.py` reads/writes Firestore data and supports direct `?order_id=` links.
6. The newer web stack uses `src/web_api/app.py` as a FastAPI backend and `frontend/` as a separate Next.js frontend.

## Project Layout

```text
super-order-automation/
├── frontend/              # Next.js frontend for the newer dashboard experience
├── src/
│   ├── cloud_functions/   # order_bot, process_order_event, renew_watch
│   ├── core/              # pipeline orchestration, processing, validation, domain logic
│   ├── dashboard/         # Streamlit UI, auth, inbox, order session, management pages
│   ├── data/              # Firestore-backed services for orders, items, suppliers
│   ├── export/            # ERP/export Excel generation
│   ├── extraction/        # local detection, Gemini prompts/schemas, model client
│   ├── ingestion/         # Gmail, GCS, Pub/Sub, Firestore write helpers
│   └── shared/            # config, logging, models, translations, utilities
├── scripts/               # maintenance, migration, and audit utilities
├── tests/                 # unit and integration-oriented tests
├── deploy.py              # backend deployment helper
├── deploy_ui.py           # Cloud Run dashboard deployment helper
└── main.py                # Cloud Function entrypoint imports
```

## Stack

- Python 3.11
- Google Gemini via `google-genai`
- Google Cloud Functions (2nd gen), Cloud Run, Pub/Sub, Cloud Storage, Firestore
- Streamlit
- FastAPI
- Next.js 15 / React 19 / Tailwind CSS v4
- Pydantic / pydantic-settings
- `uv` for dependency management

## Configuration

Configuration is loaded from environment variables and `.env` via [`src/shared/config.py`](/mnt/c/Dev/super-order-automation/src/shared/config.py).

Important variables currently used by the app and deployment scripts include:

- `GCP_PROJECT_ID`
- `GCP_REGION` or `GCP_LOCATION`
- `WEB_UI_URL`
- `GEMINI_API_KEY` and/or Google Cloud project auth for Gemini access
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID`
- `ALLOWED_EMAILS`
- `COOKIE_SECRET`
- `TEST_ORDER_EMAILS`
- `BLACKLIST_IDS`, `BLACKLIST_NAMES`, `EXCLUDED_EMAILS`

Use [`.env.example`](/mnt/c/Dev/super-order-automation/.env.example) as the starting point for local setup.

## New Frontend

The repository currently has two UI paths:

- `src/dashboard/`: the existing Streamlit app
- `frontend/`: the newer Next.js frontend

The new frontend is a separate web app that talks to the FastAPI backend in `src/web_api/app.py`. It is intended to replace the Streamlit experience over time, starting with inbox review, item management, supplier management, uploads, and order detail flows.

For local development, the Next.js app runs on `http://localhost:3000` and the FastAPI backend runs on `http://localhost:8000`.

## Local Development

Install dependencies:

```bash
uv sync --dev
```

### Daily Local Workflow For The New Frontend

Backend API:

```bash
uv run uvicorn src.web_api.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Then open:

- `http://localhost:3000` for the Next.js frontend
- `http://127.0.0.1:8000/health` to verify the FastAPI backend is up

The frontend defaults to the local API base URL, so for normal local use you usually do not need extra frontend env vars.

### Streamlit Dashboard

If you need to run the existing Streamlit app instead:

```bash
uv run streamlit run src/dashboard/app.py
```

Run tests:

```bash
uv run pytest
```

Run a focused test file:

```bash
uv run pytest tests/test_processor_fn.py -q
```

Lint and format:

```bash
uv run ruff check .
uv run ruff format .
uv run pre-commit run --all-files
```

Refresh deployable requirements after dependency changes:

```bash
uv export --format requirements-txt > requirements.txt
```

## Dashboard Auth

The dashboard currently enforces application-level login in Streamlit through [`src/dashboard/auth.py`](/mnt/c/Dev/super-order-automation/src/dashboard/auth.py).

- Google OAuth is supported.
- Microsoft OAuth is also supported.
- Access is restricted with `ALLOWED_EMAILS`, which accepts exact emails and domain suffix rules such as `@example.com`.
- In local development, a persistent fallback cookie secret can be generated automatically if `COOKIE_SECRET` is not set.

## Deployment

Deploy backend resources:

```bash
uv run python deploy.py
```

`deploy.py` currently manages backend deployment concerns including secret upload, Gmail watch renewal, the ingestion function, the processor function, and the watch-renewal function. Run `uv run python deploy.py --help` for current flags.

Deploy the Streamlit dashboard to Cloud Run:

```bash
uv run python deploy_ui.py
```

`deploy_ui.py` builds the container with `cloudbuild.yaml`, generates an env-vars file from `.env`, and deploys the `order-dashboard` Cloud Run service.

## Testing Coverage Areas

The current test suite covers core processing and several recent app behaviors, including:

- processor Cloud Function flow
- ingestion service behavior
- dashboard auth
- frontend/dashboard routing
- order test classification
- order session state
- config/auth parsing

## Notes

- The processor uses idempotency tracking to avoid duplicate Pub/Sub handling.
- Orders can be marked as test orders automatically based on `TEST_ORDER_EMAILS` or adjusted later from the dashboard.
- The dashboard supports manual file upload in addition to email-driven ingestion.
