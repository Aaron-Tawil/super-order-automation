# Automation Pipeline Design Document

## 1. High-Level Architecture Diagram

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

## 2. Modular Python Folder Structure

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

## 3. Pydantic Schema Design

Handles the complex financial logic (Gross vs Net, VAT status, hidden discounts). See `src/shared/models.py`.

```python
class VatStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    EXEMPT = "EXEMPT"

class LineItem(BaseModel):
    barcode: Optional[str]
    description: str
    quantity: float
    
    # Financials
    raw_unit_price: float
    vat_status: VatStatus
    discount_percentage: float
    
    # Promotion handling
    paid_quantity: Optional[float]
    bonus_quantity: Optional[float]
    
    # Calculated fields
    final_net_price: float

class ExtractedOrder(BaseModel):
    invoice_number: Optional[str]
    date: str
    currency: str = "USD"
    
    # Supplier identification
    supplier_name: Optional[str]
    supplier_code: Optional[str]
    supplier_global_id: Optional[str]
    
    # Discounts
    global_discount_percentage: Optional[float]
    total_invoice_discount_amount: float
    
    line_items: List[LineItem]
    warnings: List[str]
```

## 4. Supplier Profile System

We store parsing rules and supplier metadata in Firestore.
*   **Logic**:
    1.  **Ingestion**: Detects specific known senders.
    2.  **Extraction**: Queries Firestore for supplier-specific prompts or instructions.
    3.  **UI**: Allows editing supplier definitions (names, map-codes) via `supplier_management.py`.

## 5. Security Note

*   **Design Goal**: Use Google Identity-Aware Proxy (IAP) to protect the Cloud Run service.
*   **Current Implementation**: Cloud Run service is deployed with `--allow-unauthenticated` for MVP ease of access. 
*   **Future Hardening**: Re-enable internal ingress only and configure Load Balancer + IAP.
