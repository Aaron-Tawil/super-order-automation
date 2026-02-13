# Super Order Automation

Complete automation pipeline for handling store orders, invoices, and supplier management. This system ingests emails (PDFs/Excels) from suppliers, extracts line-item data using Google Gemini model, and provides a Streamlit dashboard for review and export.

## Features

*   **Automated Ingestion**: Monitors Gmail for new orders and saves attachments to Google Cloud Storage.
*   **AI Extraction**: Uses Vertex AI (Gemini model) to parse complex invoices (PDF, Images) and Extract line items, prices, and discounts.
*   **Validation Logic**: Auto-validates extracted data (sanity checks on prices, VAT calculations, and discounts).
*   **Interactive Dashboard**: Streamlit-based UI to:
    *   Review and edit extracted orders.
    *   Manage suppliers (custom names, codes, contacts).
    *   Manage product items (barcodes, descriptions).
*   **Export**: Generates valid Excel files ready for ERP import.

## Project Structure

```text
super-order-automation/
├── src/
│   ├── ingestion/       # Cloud Functions for Gmail watching & file saving
│   ├── extraction/      # Vertex AI Gemini client & prompts
│   ├── dashboard/       # Streamlit Web UI (Order Review, Supplier/Item Mgmt)
│   ├── data/            # Firestore logic (Items, Suppliers)
│   ├── export/          # Excel generation logic
│   └── shared/          # Pydantic models & logging
├── scripts/             # Utility scripts
├── deploy.py            # Deployment script for Order Bot (Backend)
├── deploy_ui.py         # Deployment script for Dashboard (Frontend)
└── DESIGN.md            # Detailed architecture documentation
```

## Quick Start / Deployment

This project relies on Google Cloud Platform services (Cloud Functions, Cloud Run, Firestore, Vertex AI).

### 1. Backend (Order Bot)
Deploy the email ingestion and extraction logic:
```bash
python deploy.py
```

### 2. Frontend (Dashboard)
Deploy the Streamlit UI to Cloud Run:
```bash
python deploy_ui.py
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed environment setup and troubleshooting.

## Local Development

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run Dashboard locally**:
    ```bash
    streamlit run src/dashboard/app.py
    ```

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
                                   |   (Ingestion)   | <-------+
                                   +--------+--------+         |
                                            |                  |
                                            | Save Raw File    |
                                            v                  |
                                   +--------+--------+         |
                                   |  Cloud Storage  |         |
                                   |  (Raw Bucket)   |         |
                                   +--------+--------+         |
                                            |                  |
                                            v                  |
                                   +--------+--------+         |
                                   |  Cloud Function |         |
                                   |   (Extraction)  |         |
                                   +--------+--------+         |
                                            |                  |
                                     Vertex AI (Gemini)        |
                                            |                  |
                                            v                  |
                                   +--------+--------+         |
                                   |    Firestore    |         |
                                   |  (Order State)  |         |
                                   +--------+--------+         |
                                            ^                  |
                                            |                  |
                                   +--------+--------+         |
                                   |    Cloud Run    |         |
                                   |   (Streamlit)   | <-------+
                                   +-----------------+
                                            |
                                            v
                                   +--------+--------+
                                   |  Final Export   |
                                   | (Excel/ERP API) |
                                   +-----------------+
```

### Modular Python Folder Structure

```text
super-order-automation/
├── src/
│   ├── ingestion/
│   │   ├── main.py              # Cloud Function: Gmail Process
│   │   ├── email_processor.py   # Email attachment handling logic
│   │   ├── gcs_writer.py        # Cloud Storage upload logic
│   │   └── gmail_watch.py       # Gmail push notification setup
│   ├── extraction/
│   │   ├── main.py              # Cloud Function: Triggered by GCS upload
│   │   ├── vertex_client.py     # Vertex AI Client wrapper
│   │   └── prompts.py           # Gemini system instructions
│   ├── export/
│   │   ├── excel_generator.py   # Pandas logic to format final output
│   │   └── utils.py             # Export helpers
│   ├── dashboard/
│   │   ├── app.py               # Streamlit entry point & Main Dashboard
│   │   ├── supplier_management.py # UI for managing suppliers
│   │   ├── items_management.py  # UI for managing items/barcodes
│   │   └── components.py        # UI widgets
│   ├── data/
│   │   ├── firestore_client.py  # DB connection
│   │   ├── supplier_service.py  # Supplier CRUD & caching
│   │   └── items_db.py          # Items/Product CRUD
│   └── shared/
│   │   ├── models.py            # Pydantic Schemas (ExtractedOrder, LineItem)
│   │   ├── session_store.py     # Session handling using Firestore
│   │   ├── validation.py        # Data validation rules
│   │   └── logger.py            # Structured logging
├── deploy.py                    # Deploy script for Backend
├── deploy_ui.py                 # Deploy script for Frontend
└── README.md
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
