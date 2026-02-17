# Super Order Automation

Complete automation pipeline for handling store orders, invoices, and supplier management. This system ingests emails (PDFs/Excels) from suppliers, extracts line-item data using Google Gemini model, and provides a Streamlit dashboard for review and export.

## Features

*   **Automated Ingestion**: Monitors Gmail for new orders and saves attachments to Google Cloud Storage.
*   **Asynchronous Pipeline**: Decouples email handling from AI processing using Pub/Sub for high reliability and retries.
*   **AI Extraction**: Uses Vertex AI (Gemini model) to parse complex invoices (PDF, Images) and Extract line items, prices, and discounts.
*   **Validation Logic**: Auto-validates extracted data (sanity checks on prices, VAT calculations, and discounts).
*   **Interactive Dashboard**: Streamlit-based UI to review orders, manage suppliers, and barcodes.
*   **Export**: Generates valid Excel files ready for ERP import.

## Architecture & Design

### High-Level Architecture Diagram

```ascii
                                   +-----------------+
                                   |  Supplier Email |
                                   | (PDFs/Excels)   |
                                   +--------+--------+
                                            |
                                            v
                                   +--------+--------+
                                   |  Cloud Function |
                                   |   (order-bot)   | 
                                   +--------+--------+
                                     /              \
                       1. Save File /                \ 2. Publish Event
                                   v                  v
                          +--------------+    +-----------------------+
                          | Cloud Storage|    | Pub/Sub Topic         |
                          | (Raw Bucket) |    | order-ingestion-topic |
                          +--------------+    +----------+------------+
                                                         |
                                                         v
                                              +-----------------------+
                                              | Cloud Function        |
                                              | (process-order-event) |
                                              +----------+------------+
                                                         |
                                                  Vertex AI (Gemini)
                                                         |
                                                         v
                                              +-----------------------+
                                              |       Firestore       |
                                              |     (Order State)     |
                                              +----------+------------+
                                                         ^
                                                         |
                                              +----------+------------+
                                              |       Cloud Run       |
                                              |      (Streamlit)      |
                                              +----------+------------+
                                                         |
                                                         v
                                              +-----------------------+
                                              |     Final Export      |
                                              |    (Excel / ERP)      |
                                              +-----------------------+
```

## Project Structure

```text
super-order-automation/
├── src/
│   ├── ingestion/       # Gmail monitoring, GCS uploads, and Event publishing
│   ├── functions/       # Cloud Function entry points (process-order-event)
│   ├── extraction/      # Vertex AI Gemini client & prompts
│   ├── core/            # Business logic: Processing, Validation, Promotions
│   ├── dashboard/       # Streamlit Web UI
│   ├── data/            # Firestore service layers (Items, Suppliers)
│   ├── export/          # Excel generation logic
│   └── shared/          # Pydantic models, Config, and Logger
├── deploy.py            # Deployment script for Backend (Functions + Pub/Sub)
├── deploy_ui.py         # Deployment script for Dashboard (Cloud Run)
└── requirements.txt     # Managed via uv
```

## Quick Start / Deployment

### 1. Backend (Cloud Functions)
Deploy the ingestion bot, the processing service, and setup Pub/Sub topics:
```bash
uv run python deploy.py
```

### 2. Frontend (Dashboard)
Build and deploy the Streamlit UI to Cloud Run:
```bash
uv run python deploy_ui.py
```

## Local Development

1.  **Install dependencies**:
    ```bash
    uv sync
    ```
2.  **Run Dashboard locally**:
    ```bash
    uv run streamlit run src/dashboard/app.py
    ```



### Supplier Profile System

We store parsing rules and supplier metadata in Firestore.
1.  **Ingestion**: Detects specific known senders.
2.  **Extraction**: Queries Firestore for supplier-specific prompts or instructions.
3.  **UI**: Allows editing supplier definitions (names, map-codes) via `supplier_management.py`.

### Security Note

*   **Design Goal**: Use Google Identity-Aware Proxy (IAP) to protect the Cloud Run service.
*   **Current Implementation**: Cloud Run service is deployed with `--allow-unauthenticated` for MVP ease of access. 
*   **Future Hardening**: Re-enable internal ingress only and configure Load Balancer + IAP.
