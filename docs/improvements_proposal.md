# Dashboard Improvement Proposal (Expanded)

## 1) Product Direction
The dashboard should evolve from a single-order editor into a two-level workspace:

1. `Inbox Dashboard` for operations and monitoring all processed orders.
2. `Order Workspace` for one order at a time (deep link from email), including a prompt playground.

This keeps the email flow intact while adding an operations view for scale.

## 2) Primary Windows

### A. Inbox Dashboard (All Orders)
Purpose: fast triage, search, filtering, and navigation into each order.

Core components:
- Top KPIs:
  - total orders (selected date range)
  - completed
  - needs review
  - failed
  - unknown supplier count
- Search bar (global):
  - invoice number
  - supplier code/name
  - sender email
  - filename
  - barcode/item text (see data model notes)
- Filter panel:
  - status (multi-select: `PROCESSING`, `COMPLETED`, `NEEDS_REVIEW`, `FAILED`)
  - supplier
  - date range (`created_at`)
  - order type (`Real` / `Test`) with default view set to `Real` only
  - only unknown supplier
  - has warnings
- Orders table (sortable/paginated):
  - created at
  - status
  - supplier (code + name)
  - invoice number
  - sender
  - line items count
  - warnings count
  - processing cost (ILS)
  - actions: `Open`, `Copy Link`
- Bulk actions (phase 2):
  - mark selected as needs review
  - export selected metadata to CSV

Recommended UX behavior:
- Default sort: newest first.
- Keep filters in URL query params so views are shareable.
- Use saved views (phase 2): “Needs Review”, “Unknown Supplier”, “Today”.

---

### B. Order Workspace (Per Order Link)
Purpose: full review/edit of one order + experimentation with custom extraction instructions.

Entry points:
- From email link (`?session=<id>`) — already exists.
- From Inbox row action (`Open`).

Layout:
- Header:
  - order status badge
  - supplier and invoice meta
  - created time, sender, filename
  - quick actions: download Excel, copy order link
- Main tabs:
  - `Extracted Data` (existing editor, warnings, new items)
  - `AI Insights` (phase reasoning, math/qty reasoning, notes)
  - `Prompt Playground` (new)
  - `History` (new, lightweight audit trail)

Recommended actions:
- `Retry with instructions` (existing behavior, improved UX)
- `Approve order` / `Mark needs review`
- `Save supplier instructions` (from Playground)

## 3) Prompt Playground (Per Order)
This is the most valuable advanced feature and should be isolated from production data until user confirms.

### Goals
- Let power users test instruction changes safely.
- Show before/after impact quickly.
- Allow one-click promotion to supplier-level permanent instructions.

### Playground UX
- Preload text area with current supplier `special_instructions`.
- Show two run modes:
  - `Test on current document` (default)
  - `Test on uploaded sample` (phase 2)
- Run output panel:
  - parsed order preview table
  - diff vs baseline extraction (line count changed, quantity/price changes, warnings delta)
  - runtime + estimated AI cost
- Save controls:
  - `Use only for this order` (ephemeral)
  - `Save to supplier` (persistent DB write)
  - optional note: “why changed”

### Save-to-DB safety checks
Before writing to supplier DB:
- require explicit confirmation modal
- show supplier code being updated
- show old vs new instruction preview
- log who changed it + timestamp + optional note

### Data to persist for traceability
- `supplier_instruction_versions` collection (recommended):
  - `supplier_code`
  - `instructions`
  - `changed_by`
  - `changed_at`
  - `source_order_id` / `source_session_id`
  - `change_note`

## 4) Data Model and Backend Adjustments

### Current reality
- `sessions` collection stores share-link payload (order + metadata) with expiry.
- `orders` collection exists but currently has limited dashboard fields.
- `processing_events` tracks pipeline statuses.

### Recommended dashboard read model
Either enrich `orders` docs directly or create `order_views` docs (denormalized for UI queries).

Suggested fields (minimal for Inbox):
- `order_id` (doc id)
- `session_id` (for deep link)
- `event_id`
- `created_at`, `updated_at`
- `status`
- `supplier_code`, `supplier_name`
- `invoice_number`
- `sender`, `subject`, `filename`
- `line_items_count`
- `warnings_count`
- `has_warnings`
- `is_unknown_supplier`
- `processing_cost_ils`
- `is_test`
- `search_tokens` (optional)

### Firestore index plan
- `(status, created_at desc)`
- `(supplier_code, created_at desc)`
- `(is_unknown_supplier, created_at desc)`
- `(has_warnings, created_at desc)`
- `(created_at desc)`

If “items contained” filter is mandatory:
- Add `item_barcodes` array (normalized), then use `array_contains`.
- Note: for free-text item description search at scale, use a dedicated search engine later.

## 5) Streamlit Architecture Plan
Refactor current `src/dashboard/app.py` into page modules to keep complexity manageable.

Proposed structure:
- `src/dashboard/pages/inbox.py`
- `src/dashboard/pages/order_workspace.py`
- `src/dashboard/components/order_table.py`
- `src/dashboard/components/prompt_playground.py`
- `src/dashboard/services/order_repository.py`

Routing:
- Keep sidebar navigation.
- Support query params:
  - `?page=inbox`
  - `?page=order&session=<id>`
  - optional `?order_id=<id>`

## 6) Status Model (Unified)
Standardize one status enum for UI and backend:
- `PROCESSING`
- `COMPLETED`
- `NEEDS_REVIEW`
- `FAILED`
- `ARCHIVED` (optional later)

Rules:
- extraction errors => `FAILED`
- warnings/unknown supplier can auto-set `NEEDS_REVIEW`
- manual approval can move to `COMPLETED`

## 7) Rollout Phases

### Phase 1 (MVP - high impact)
- Inbox page with table + search + status/supplier/date filters
- Open order from table
- Keep existing order editor behavior

### Phase 2
- Prompt Playground tab in order workspace
- Test run with custom instructions
- Save instructions permanently to supplier DB with confirmation
- Basic audit log for instruction updates

### Phase 3
- Diff view quality metrics (before/after)
- Saved filter presets in Inbox
- Bulk actions and CSV export

### Phase 4
- Analytics dashboard (supplier success rate, retry rate, failure reasons)
- Performance optimization + pagination tuning

## 8) Design Recommendations
- Keep current simple visual style, but enforce stronger hierarchy:
  - sticky filter bar in Inbox
  - clear status color coding
  - persistent action bar in Order Workspace
- Prefer fewer widgets per row and obvious action grouping:
  - “Test prompt” separate from “Save permanently” to prevent accidental writes
- Add empty/loading/error states for each window.

## 9) Acceptance Criteria (First Milestone)
- User can view all orders in one Inbox table.
- User can filter by status, supplier, date range.
- User can search and open any order into Order Workspace.
- Email deep link still opens the correct order.
- Prompt Playground allows test run with custom instructions.
- User can save instructions to supplier DB with confirmation.
- All critical actions are logged with user + timestamp.

## 10) Risks and Mitigations
- Risk: Firestore query performance degrades with large order volume.
  - Mitigation: denormalized read model + strict indexes + pagination.
- Risk: accidental overwrite of supplier instructions.
  - Mitigation: confirmation modal + version history + rollback option.
- Risk: confusion between temporary and permanent instructions.
  - Mitigation: explicit dual-action buttons and warning copy.
