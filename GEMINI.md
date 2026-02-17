# Super Order Automation

## Project Overview
This project is an automated pipeline for handling store orders and invoices. It ingests emails (containing PDFs or Excel files) from suppliers, extracts line-item data using Google's Vertex AI (Gemini models), and provides a Streamlit dashboard for review and management.

**Key Technologies:**
*   **Language:** Python 3.11
*   **AI/ML:** Google Vertex AI (Gemini)
*   **Cloud Platform:** Google Cloud Platform (GCP)
    *   **Compute:** Cloud Functions (2nd Gen), Cloud Run
    *   **Storage:** Cloud Storage (GCS), Firestore
    *   **Messaging:** Pub/Sub
*   **Frontend:** Streamlit
*   **Dependency Management:** `uv` (preferred) or `pip`

**Architecture:**
1.  **Ingestion:** A Cloud Function (`order-bot`) monitors Gmail via push notifications (Pub/Sub), downloads attachments, and uploads them to a GCS bucket.
2.  **Extraction:** A second Cloud Function (`process-order-event`) triggers on GCS upload (or Pub/Sub event), uses Vertex AI to extract data, and saves the result to Firestore.
3.  **Dashboard:** A Streamlit application hosted on Cloud Run allows users to review extracted orders, manage supplier mappings, and export data to Excel.

## Building and Running

### Prerequisites
*   Python 3.11+
*   Google Cloud SDK (`gcloud`) installed and authenticated
*   `.env` file with necessary environment variables (see `.env.example` if available, or `deploy.py` for required vars)

### Local Development
1.  **Install Dependencies:**
    ```bash
    # Using pip
    pip install -r requirements.txt
    
    # OR using uv
    uv sync
    ```

2.  **Run Dashboard Locally:**
    ```bash
    streamlit run src/dashboard/app.py
    ```

3.  **Linting & Formatting:**
    The project uses `ruff` for linting and formatting.
    ```bash
    ruff check .
    ruff format .
    ```

4.  **Testing:**
    ```bash
    pytest
    ```

### Deployment
The project includes helper scripts for deploying to GCP.

**1. Backend (Cloud Functions)**
Deploys the email ingestion and order processing functions.
```bash
python deploy.py
# Options:
#   --skip-secret       Skip updating the Gmail token in Secret Manager
#   --skip-watch        Skip renewing the Gmail watch (local)
#   --skip-renew-watch  Skip deploying the watch renewal function
```

**2. Frontend (Cloud Run)**
Builds the container image and deploys the Streamlit app.
```bash
python deploy_ui.py
```

## Development Conventions

*   **Project Structure:**
    *   `src/ingestion/`: Logic for Gmail monitoring and file upload.
    *   `src/extraction/`: Vertex AI integration and prompt logic.
    *   `src/dashboard/`: Streamlit UI components and pages.
    *   `src/data/`: Database access layers (Firestore).
    *   `src/shared/`: Shared models (Pydantic), logging, and config.
    *   `scripts/`: Utility scripts for maintenance and migration.

*   **Configuration:**
    *   Environment variables are loaded from `.env` for local development.
    *   `src/shared/config.py` manages application settings.

*   **Code Style:**
    *   Follows PEP 8 guidelines.
    *   Enforced by `ruff`.
    *   Type hints are encouraged (using `typing` module).

*   **Logging:**
    *   Structured logging is used throughout (`src.shared.logger`).
