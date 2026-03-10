# Super Order Automation

## Project Overview
This project is an automated pipeline for handling store orders and invoices. It ingests supplier emails containing PDF or Excel attachments, extracts structured order data with Gemini-based logic, persists the results to Firestore, and provides a Streamlit dashboard for review and correction.

**Key Technologies:**
*   **Language:** Python 3.11
*   **AI/ML:** Google Gemini via `google-genai`
*   **Cloud Platform:** Google Cloud Platform (GCP)
    *   **Compute:** Cloud Functions (2nd Gen), Cloud Run
    *   **Storage:** Cloud Storage (GCS), Firestore
    *   **Messaging:** Pub/Sub
*   **Frontend:** Streamlit
*   **Dependency Management:** `uv`

**Architecture:**
1.  **Ingestion:** A Cloud Function (`order-bot`) is triggered from Gmail push notifications via Pub/Sub and runs the unread-email ingestion flow.
2.  **Eventing:** The ingestion layer uploads attachments to GCS and publishes `OrderIngestedEvent` messages.
3.  **Processing:** `process-order-event` downloads the file, runs supplier detection plus extraction/post-processing, stores orders in Firestore, and generates outbound Excel attachments.
4.  **Watch renewal:** `renew_watch` is an HTTP Cloud Function intended to be called by Cloud Scheduler.
5.  **Dashboard:** A Streamlit app hosted on Cloud Run allows users to review inbox orders, open permanent `order_id` links, upload files manually, manage suppliers/items, and adjust test-order classification.

## Building and Running

### Prerequisites
*   Python 3.11+
*   Google Cloud SDK (`gcloud`) installed and authenticated
*   `.env` file with necessary environment variables (see [`.env.example`](/mnt/c/Dev/super-order-automation/.env.example))

### Local Development
1.  **Install Dependencies:**
    ```bash
    uv sync --dev
    ```

2.  **Run Dashboard Locally:**
    ```bash
    uv run streamlit run src/dashboard/app.py
    ```

3.  **Linting & Formatting:**
    The project uses `ruff` for linting and formatting.
    ```bash
    uv run ruff check .
    uv run ruff format .
    ```

4.  **Testing:**
    ```bash
    uv run pytest
    ```

### Deployment
The project includes helper scripts for deploying to GCP.

**1. Backend (Cloud Functions)**
Deploys the ingestion, processor, and watch-renewal backend resources.
```bash
uv run python deploy.py
# Options:
#   --skip-secret       Skip updating the Gmail token in Secret Manager
#   --skip-watch        Skip renewing the Gmail watch (local)
#   --skip-renew-watch  Skip deploying the watch renewal function
#   --skip-bot          Skip deploying the ingestion function
#   --skip-processor    Skip deploying the processor function
```

**2. Frontend (Cloud Run)**
Builds the container image and deploys the Streamlit app.
```bash
uv run python deploy_ui.py
```

## Development Conventions

*   **Project Structure:**
    *   `src/ingestion/`: Logic for Gmail monitoring and file upload.
    *   `src/extraction/`: Local supplier detection, Gemini integration, and prompt logic.
    *   `src/dashboard/`: Streamlit UI, OAuth auth, inbox, and order management pages.
    *   `src/data/`: Firestore-backed access layers for orders, items, and suppliers.
    *   `src/cloud_functions/`: `order_bot`, `process_order_event`, and `renew_watch`.
    *   `src/shared/`: Shared models (Pydantic), logging, and config.
    *   `scripts/`: Utility scripts for maintenance and migration.

*   **Configuration:**
    *   Environment variables are loaded from `.env` for local development.
    *   `src/shared/config.py` manages application settings.
    *   Dashboard auth currently relies on OAuth client credentials, `ALLOWED_EMAILS`, and `COOKIE_SECRET`.
    *   `TEST_ORDER_EMAILS` controls automatic test-order marking.

*   **Code Style:**
    *   Use modern Python 3.11 style with type hints.
    *   Import ordering and formatting are enforced by `ruff`.

*   **Logging:**
    *   Structured logging is used throughout (`src.shared.logger`).
