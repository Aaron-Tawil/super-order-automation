# Firestore Audit Report

- Generated at: `2026-03-03T14:34:26.518317+00:00`
- Project: `super-home-automation`
- Max docs scanned per collection: `250`
- Max recursion depth: `3`

## Root Collections
- Found: `items, orders, processed_messages, processed_order_events, processing_events, sessions, suppliers`
- Unknown (not referenced in code): `(none)`
- Missing expected: `(none)`

## Collection Details
### `items`
- Estimated doc count: `53965`
- Scanned docs: `250`
- Fully scanned: `False`
- Subcollections seen: `(none)`
- Fields and observed types:
  - `item_code` -> `str:242, null:8`
  - `name` -> `str:250`
  - `note` -> `null:250`
- Sample documents:
  - `041604341724` (3 fields): `item_code, name, note`
  - `0416060000001` (3 fields): `item_code, name, note`
  - `05535002381` (3 fields): `item_code, name, note`
  - `05535002581` (3 fields): `item_code, name, note`
  - `0608275991445` (3 fields): `item_code, name, note`
  - `0608614329212` (3 fields): `item_code, name, note`
  - `0622356239769` (3 fields): `item_code, name, note`
  - `0693493039437` (3 fields): `item_code, name, note`
  - `0693493266697` (3 fields): `item_code, name, note`
  - `0710497339117` (3 fields): `item_code, name, note`

### `orders`
- Estimated doc count: `74`
- Scanned docs: `74`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Fields and observed types:
  - `ai_metadata` -> `dict:24`
  - `created_at` -> `DatetimeWithNanoseconds:74`
  - `currency` -> `str:74`
  - `document_total_quantity` -> `null:38, float:34`
  - `document_total_with_vat` -> `float:68, null:4`
  - `document_total_without_vat` -> `float:22, null:2`
  - `gcs_uri` -> `str:74`
  - `global_discount_percentage` -> `float:72`
  - `invoice_number` -> `str:67, null:7`
  - `is_math_valid` -> `null:20, bool:4`
  - `is_qty_valid` -> `null:20, bool:4`
  - `line_items` -> `list:74`
  - `math_reasoning` -> `null:23, str:1`
  - `notes` -> `null:15, str:9`
  - `processing_cost` -> `float:29`
  - `processing_cost_ils` -> `float:29`
  - `qty_reasoning` -> `null:23, str:1`
  - `status` -> `str:74`
  - `supplier_code` -> `str:69, null:3`
  - `supplier_email` -> `null:72`
  - `supplier_global_id` -> `null:72`
  - `supplier_name` -> `str:71, null:3`
  - `supplier_phone` -> `null:72`
  - `total_invoice_discount_amount` -> `float:74`
  - `usage_metadata` -> `null:29`
  - `vat_status` -> `str:6`
  - `warnings` -> `list:72`
- Sample documents:
  - `0JxVTIH3eI6hNueNpmvw` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`
  - `1U7v7n8lCOkgB9BPN0Tw` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`
  - `1bAebb1pL5U1SSJDIolQ` (19 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, processing_cost, processing_cost_ils, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, usage_metadata, warnings`
  - `28AaWVsaYSwZeRPVEF5i` (26 fields): `ai_metadata, created_at, currency, document_total_quantity, document_total_with_vat, document_total_without_vat, gcs_uri, global_discount_percentage, invoice_number, is_math_valid, is_qty_valid, line_items, math_reasoning, notes, processing_cost, processing_cost_ils, qty_reasoning, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, usage_metadata, warnings`
  - `34RmyUoIPiY1A0QHGi04` (27 fields): `ai_metadata, created_at, currency, document_total_quantity, document_total_with_vat, document_total_without_vat, gcs_uri, global_discount_percentage, invoice_number, is_math_valid, is_qty_valid, line_items, math_reasoning, notes, processing_cost, processing_cost_ils, qty_reasoning, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, usage_metadata, vat_status, warnings`
  - `5a0v1MKi086szmrOtRm9` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`
  - `6N4HkJ2hXJUZfD48PAM0` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`
  - `6lWu6HXzlPumVzaWortN` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`
  - `8uWNo4ih9NsgM9OB6fCE` (8 fields): `created_at, currency, gcs_uri, invoice_number, line_items, status, supplier_name, total_invoice_discount_amount`
  - `A2hT33yhdCHuousjB4My` (16 fields): `created_at, currency, document_total_quantity, document_total_with_vat, gcs_uri, global_discount_percentage, invoice_number, line_items, status, supplier_code, supplier_email, supplier_global_id, supplier_name, supplier_phone, total_invoice_discount_amount, warnings`

### `processed_messages`
- Estimated doc count: `91`
- Scanned docs: `91`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Missing fields vs expected: `error_message`
- Fields and observed types:
  - `attempt_count` -> `int:2`
  - `created_at` -> `DatetimeWithNanoseconds:91`
  - `expires_at` -> `DatetimeWithNanoseconds:91`
  - `processed_at` -> `DatetimeWithNanoseconds:88, null:3`
  - `status` -> `str:91`
- Sample documents:
  - `19c488620faaf571` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c489e48db34b4c` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4bd5ab5035bf4` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4bf4dbe3ed0d2` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4c2cf16d25c0e` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4c30b424b3252` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4c37790d96d1f` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4ea5697f44877` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4ebaada8683ff` (4 fields): `created_at, expires_at, processed_at, status`
  - `19c4ebca0f2e7aca` (4 fields): `created_at, expires_at, processed_at, status`

### `processed_order_events`
- Estimated doc count: `2`
- Scanned docs: `2`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Missing fields vs expected: `error_message`
- Fields and observed types:
  - `attempt_count` -> `int:2`
  - `created_at` -> `DatetimeWithNanoseconds:2`
  - `expires_at` -> `DatetimeWithNanoseconds:2`
  - `processed_at` -> `DatetimeWithNanoseconds:2`
  - `status` -> `str:2`
- Sample documents:
  - `2026-03-02T14:34:54.613005+00:00` (5 fields): `attempt_count, created_at, expires_at, processed_at, status`
  - `2026-03-02T21:14:51.227129+00:00` (5 fields): `attempt_count, created_at, expires_at, processed_at, status`

### `processing_events`
- Estimated doc count: `2`
- Scanned docs: `2`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Fields and observed types:
  - `created_at` -> `DatetimeWithNanoseconds:2`
  - `details` -> `dict:2`
  - `event_id` -> `str:2`
  - `stage` -> `str:2`
  - `status` -> `str:2`
  - `updated_at` -> `DatetimeWithNanoseconds:2`
- Sample documents:
  - `2026-03-02T14:34:54.613005+00:00` (6 fields): `created_at, details, event_id, stage, status, updated_at`
  - `2026-03-02T21:14:51.227129+00:00` (6 fields): `created_at, details, event_id, stage, status, updated_at`

### `sessions`
- Estimated doc count: `182`
- Scanned docs: `182`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Fields and observed types:
  - `created_at` -> `DatetimeWithNanoseconds:182`
  - `expires_at` -> `DatetimeWithNanoseconds:182`
  - `metadata` -> `dict:182`
  - `order` -> `dict:182`
- Sample documents:
  - `01669b14-a00d-4606-a3bc-509e57b35552` (4 fields): `created_at, expires_at, metadata, order`
  - `01b3b5f2-5fc5-4e80-b0f5-d3ec9215310f` (4 fields): `created_at, expires_at, metadata, order`
  - `026259d2-c7d0-4c8b-a5b6-cf045d904932` (4 fields): `created_at, expires_at, metadata, order`
  - `058b13fa-2e5d-443c-ae9a-8615937d40ca` (4 fields): `created_at, expires_at, metadata, order`
  - `0662f639-05c2-44c2-8acb-1dc5bd909edb` (4 fields): `created_at, expires_at, metadata, order`
  - `081ca217-6ae9-412a-b699-43728fcab8a2` (4 fields): `created_at, expires_at, metadata, order`
  - `082dd3de-b1dc-4997-99ce-22304bf22452` (4 fields): `created_at, expires_at, metadata, order`
  - `0934809c-7c2f-47ce-bdc7-5808478b4db2` (4 fields): `created_at, expires_at, metadata, order`
  - `09ccf80e-e3ad-405c-9e43-3c2accd6de28` (4 fields): `created_at, expires_at, metadata, order`
  - `0a6deb39-7765-4319-a555-80340a2454da` (4 fields): `created_at, expires_at, metadata, order`

### `suppliers`
- Estimated doc count: `211`
- Scanned docs: `211`
- Fully scanned: `True`
- Subcollections seen: `(none)`
- Missing fields vs expected: `created_at`
- Fields and observed types:
  - `additional_emails` -> `list:3`
  - `email` -> `null:119, str:91`
  - `global_id` -> `str:183, null:27`
  - `last_modified` -> `DatetimeWithNanoseconds:1`
  - `name` -> `str:210`
  - `phone` -> `str:120, null:90`
  - `special_instructions` -> `str:11`
  - `updated_at` -> `DatetimeWithNanoseconds:13`
  - `updated_by` -> `str:1`
- Sample documents:
  - `120022` (4 fields): `email, global_id, name, phone`
  - `121002` (4 fields): `email, global_id, name, phone`
  - `121012` (4 fields): `email, global_id, name, phone`
  - `121013` (4 fields): `email, global_id, name, phone`
  - `121020` (4 fields): `email, global_id, name, phone`
  - `121022` (4 fields): `email, global_id, name, phone`
  - `121023` (4 fields): `email, global_id, name, phone`
  - `121036` (4 fields): `email, global_id, name, phone`
  - `121038` (4 fields): `email, global_id, name, phone`
  - `121047` (4 fields): `email, global_id, name, phone`

## Obsolete / Unused Candidates
- Both `processed_messages` and `processed_order_events` exist; verify if dual idempotency collections are intentional.

## Notes
- Unknown collections and extra fields are candidates, not guaranteed safe to delete.
- Confirm usage via logs, dashboards, and retention requirements before cleanup.
