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
