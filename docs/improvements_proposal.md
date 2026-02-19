# Project Review & Improvements Proposal

## Executive Summary
The "Super Order Automation" project is a functional prototype that successfully integrates Gmail, Vertex AI, and a Streamlit dashboard to automate order entry. To move from a prototype to a **feature-rich, robust, and reliable production system**, several architectural refactoring steps and feature additions are recommended. 

The primary goal is to **decouple business logic from interface logic**, ensure **type safety**, and improve **observability**.

---

## 1. Architecture & Design Patterns

### Current State
- **Monolithic Scripting**: Logic is often embedded directly in `process_invoice` or `app.py`.
- **Duplication**: Similar logic potentially exists in `email_processor.py` (Cloud Function) and `app.py` (Dashboard Retry).
- **Synchronous Bottlenecks**: Email processing appears to handle heavy AI tasks synchronously.

### Recommendations

#### A. Service Layer Pattern (Refactoring) ✅ [COMPLETED]
Create a dedicated **Core Business Layer** (`src/core`) that both the Cloud Function and Streamlit App import.
- **`OrderProcessor`**: A class that handles the lifecycle of an order (Extraction -> Validation -> Database).
- **`IngestionService`**: Handles file inputs (Email, Upload) and normalizes them before processing.
- **Benefit**: "Retry" logic in the Dashboard calls the exact same code as the "New Email" logic, ensuring consistency.

#### B. Event-Driven Architecture (Async Processing)
Instead of processing the invoice *immediately* when the email arrives (which can timeout):
1.  **Ingestion Function**: Receives Gmail push -> Saves attachment to GCS -> Publishes message to Pub/Sub (`order-processing-queue`).
2.  **Processing Function**: Subscribes to `order-processing-queue` -> Downloads file -> Calls Vertex AI -> Saves to Firestore.
3.  **Benefit**: Reliability. If 100 emails arrive at once, the queue handles them without timeouts. Retries are managed by Pub/Sub dead-letter queues.

#### C. Backend API Expansion
Expand `src/api/main.py` to be the primary backend for the Streamlit App.
- Instead of Streamlit accessing Firestore directly, it should (ideally) call the API.
- This separates "Frontend" (Streamlit) from "Backend" (Data/AI logic).

---

## 2. Reliability & Robustness

### A. Structured Logging ✅ [COMPLETED]
Replace `print()` and basic `logging` with **JSON Structured Logging**.
- Use `python-json-logger` or Google Cloud Logging libraries.
- **Why?** In Cloud Run/Functions, you can query logs by `order_id`, `supplier_code`, or `severity`.
- **Status**: Implemented in `src/shared/logger.py`.

### B. Comprehensive Error Handling
Implement a centralized error handling strategy.
- Define custom exception types: `ExtractionError`, `ValidationError`, `NetworkError`.
- Ensure **all** failures end up in a "Failed Orders" queue/list in Firestore, visible in the Dashboard for manual intervention.

### C. Type Safety & Validation (Pydantic V2)
- Ensure all data passing between layers involves **Pydantic Models**.
- Use Pydantic's `ComputedField` or `field_validator` for all business rules (like VAT calculation logic), removing that logic from the generic extraction code.

### D. Testing Strategy 🔄 [IN PROGRESS]
One of the biggest missing pieces is a test suite.
1.  **Unit Tests**: Test `validate_order_totals` and `post_process_promotions` with mock data. (Implemented in `tests/`)
2.  **Integration Tests**: Test Firestore read/writes using the Local Emulator or a test project.
3.  **Snapshot Tests**: Save "Gold Standard" input PDFs and expected JSON outputs. Run these on every PR to ensure prompt changes don't break existing extraction accuracy.

---

## 3. Tech Stack & Tooling

### Recommendations
1.  **Dependency Management**: Switch to **Poetry** or **uv**. ✅ [COMPLETED]
    - Project now uses `uv`. `requirements.txt` is generated from `uv.lock`.
2.  **Linting & Formatting**: Add `ruff` (replacing flake8/isort/black). ✅ [COMPLETED]
    - Enforce code style automatically via `pre-commit` hooks.
3.  **Configuration**: Use `pydantic-settings`. ✅ [COMPLETED]
    - Strongly typed environment variables. Validation on startup (fails fast if `GCP_PROJECT_ID` is missing).
    - Status: Implemented in `src/shared/config.py`.

---

## 4. Feature Richness (UI/UX)

### A. Dashboard "Inbox"
Create a dedicated "Inbox" view in Streamlit.
- Shows all processed orders with status: `PROCESSING`, `COMPLETED`, `NEEDS_REVIEW`, `FAILED`.
- Allows users to see *live* progress of an extraction.

### B. Advanced Search & Filtering
- Add a sidebar filter to find orders by: **Supplier**, **Date Range**, **Status**, **Items contained**.
- Use Firestore composite indexes to make this fast.

### C. Supplier Management 2.0
- Add **Stats**: "Success rate per supplier".
- **Prompt Playground**: Allow power users to tweak the "Special Instructions" and *immediately test* it against a uploaded PDF in a sandbox view (without saving to the main DB).



---

## 5. Proposed Roadmap

### Phase 1: Refactoring (Robustness) - [COMPLETED]
1.  Set up **Poetry** and **Ruff**. (Done - using `uv`)
2.  Create `src/core` and move logic from `email_processor` and `vertex_client` into reusable classes. (Done)
3.  Implement **Pydantic Settings** and **Structured Logging**. (Done)

### Phase 2: Reliability (Testing & Async) - [IN PROGRESS]
1.  Add **Unit Tests** for core logic. (In Progress)
2.  Implement **Pub/Sub** pattern for email ingestion.
3.  Add "Dead Letter" handling (if AI fails 3 times, alert human).

### Phase 3: Features (UI)
1.  Build the **"Inbox"** view.
2.  Add **Analytics** and **Search** filters.


