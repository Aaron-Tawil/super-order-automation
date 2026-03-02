# Super Order Automation: Improvement Proposal v2

Date: 2026-03-02
Scope: Replace and update `docs/improvements_proposal.md` with code-based status and a practical roadmap.

## 1) Current Standing (Code-Based)

### 1.1 Architecture

Status: Partially complete

- Service-layer refactor is mostly real:
  - `OrderProcessor` exists in `src/core/processor.py`.
  - `ExtractionPipeline` exists in `src/core/pipeline.py`.
  - `IngestionService` exists in `src/ingestion/ingestor.py`.
- Event-driven flow is implemented:
  - Ingestion trigger function: `src/cloud_functions/ingestion_fn.py` (`order_bot`).
  - Processing function: `src/cloud_functions/processor_fn.py` (`process_order_event`).
  - Pub/Sub event model: `src/core/events.py`.
- API expansion is not implemented:
  - No `src/api` module or FastAPI router/app entrypoint in `src/`.

### 1.2 Reliability and Robustness

Status: Partial, with critical gaps

- Structured logging exists but is inconsistent:
  - Structured logger utility: `src/shared/logger.py`.
  - Several modules still use `logging.basicConfig`, `logging.getLogger`, or `print`.
- Error taxonomy exists but is not operational:
  - Custom exceptions defined in `src/core/exceptions.py`.
  - They are mostly not raised/propagated through the pipeline.
- Failed-order persistence is missing:
  - No dedicated failed-orders collection/service/dashboard queue.
  - Orders are saved with `status = "EXTRACTED"` in `src/ingestion/firestore_writer.py`.
  - In extraction failure paths (`process_order_event`), function may return without durable failure record.
- Idempotency exists only at Gmail message ingestion:
  - `src/shared/idempotency_service.py` protects message IDs.
  - No explicit end-to-end idempotency key for attachment-level processing.

### 1.3 Data Contracts and Type Safety

Status: Good foundation, but uneven boundaries

- Pydantic v2 models are central in `src/shared/models.py` and event models in `src/core/events.py`.
- Validation/coercion on barcodes and numeric fields is implemented.
- Some cross-layer boundaries still pass raw dict-like payloads and temporary conversions.

### 1.4 Testing

Status: In progress

- There is a meaningful unit/integration-style test set in `tests/` (processor, ingestion service, cloud function, UI smoke).
- Major gaps remain:
  - No Firestore emulator integration tests.
  - No extraction snapshot/golden tests for prompt/model regressions.
  - No contract/version tests for Pub/Sub event schemas.
- `tests/integration/simulate_email_pipeline.py` has an outdated import path (`src.functions.processor_fn`), so this helper is currently broken.

### 1.5 UI/Feature Coverage

Status: Partial

- Existing dashboard is useful for extraction review, retry, suppliers, and items.
- Missing from previous proposal:
  - No dedicated "Inbox" page for order lifecycle states (`PROCESSING`, `COMPLETED`, `NEEDS_REVIEW`, `FAILED`).
  - No robust global filtering by supplier/date/status/items for processed orders.
  - No supplier success analytics or prompt sandbox playground.

### 1.6 Ops and Security

Status: MVP-level

- Deployment flow is automated via `deploy.py`.
- Pub/Sub topics are checked/created, but dead-letter handling and replay workflows are not codified in code/deploy script.
- `renew-watch-orders` is deployed `--allow-unauthenticated` in `deploy.py`, which is acceptable for MVP but weak for production hardening.

## 2) Critique of Previous Proposal

The previous proposal was directionally right but too optimistic in completion labeling.

Main issues:

1. It marks several items as "completed" where implementation is only partial (structured logging, reliability posture).
2. It under-specifies failure-state persistence and operational recovery, which is a core production requirement for this pipeline.
3. It proposes backend API expansion without defining transition strategy from current Streamlit-direct data access.
4. It does not define measurable outcomes (SLOs, error budgets, extraction quality KPIs).
5. It treats "async via Pub/Sub" as sufficient reliability, while DLQ/replay/idempotency-by-attachment are still missing.

## 3) New Improvement Proposal

### 3.1 Outcome Targets (next 8-10 weeks)

1. Reliability: no silent drops; every ingestion event ends in a durable terminal state.
2. Operability: every order can be traced by correlation ID across ingestion, extraction, and persistence.
3. Quality: model/prompt changes cannot regress core suppliers without detection.
4. Product: operators can triage and recover failed/review-needed orders from a single Inbox UI.

### 3.2 Workstreams and Deliverables

### Workstream A: Processing State Machine and Failure Durability

Deliverables:

- Introduce canonical order/job lifecycle states:
  - `QUEUED`, `PROCESSING`, `EXTRACTED`, `NEEDS_REVIEW`, `FAILED`.
- Persist processing record at start and update at every transition.
- Add dedicated failure payload fields (`error_type`, `error_message`, `stage`, `retry_count`, `last_seen_at`).
- Ensure all exception paths in processing function write terminal failure state.

Definition of done:

- 100% of processed events are queryable in Firestore with terminal status.
- No early-return path without durable state update.

### Workstream B: Idempotency, Retries, and Replay

Deliverables:

- Add attachment-level idempotency key (example: hash of `message_id + attachment filename + blob generation`).
- Add replay-safe processing guard in `process_order_event`.
- Add operational replay script for failed events.
- Document retry policy and failure semantics.

Definition of done:

- Duplicate Pub/Sub deliveries do not create duplicate orders.
- Replay of a failed event is deterministic and auditable.

### Workstream C: Logging and Observability Standardization

Deliverables:

- Enforce `src/shared/logger.get_logger()` in all runtime modules.
- Remove ad-hoc `print`/`basicConfig` usage from production paths.
- Add correlation fields to every log line (`event_id`, `message_id`, `session_id`, `supplier_code` when known).
- Add baseline metrics counters (processed, failed, needs_review, unknown_supplier).

Definition of done:

- Log search can reconstruct full event path within 1-2 queries.

### Workstream D: Test Strategy Upgrade

Deliverables:

- Add Firestore emulator-backed integration tests for write paths and status transitions.
- Add golden extraction tests for top suppliers using frozen files and expected normalized JSON.
- Fix and maintain the `tests/integration/simulate_email_pipeline.py` helper path/runtime.
- Add CI gates for `ruff` and tests (at least smoke + core unit).

Definition of done:

- Prompt/schema changes run against goldens before merge.
- Core processing paths have deterministic pass/fail checks.

### Workstream E: Inbox and Recovery UI

Deliverables:

- Add Streamlit Inbox page listing orders/jobs with status and key metadata.
- Add filters: supplier, status, date range, invoice number, unknown supplier.
- Add operator actions: retry processing, mark reviewed, download raw/error context.
- Expose failure reason and extraction warnings in UI.

Definition of done:

- Manual recovery is possible without log digging or direct Firestore edits.

### 3.3 Suggested Delivery Phases

### Phase 1 (Weeks 1-2): Reliability Foundation

- Implement canonical status model and failure durability.
- Add attachment-level idempotency.
- Standardize logging in cloud functions + pipeline path.

### Phase 2 (Weeks 3-5): Test and Regression Safety

- Add Firestore emulator tests.
- Add golden extraction dataset and runner.
- Fix integration simulation helper and document local run flow.

### Phase 3 (Weeks 6-8): Operator Product

- Build Inbox page with filters and recovery actions.
- Add supplier-level operational stats (success/failure rate).
- Add basic prompt test sandbox (non-destructive preview only).

### 3.4 Non-Goals for This Cycle

- Full microservice split.
- Immediate replacement of Streamlit with separate SPA.
- Broad API-first redesign before stability baselines are achieved.

## 4) Priority Backlog (Actionable)

P0:

1. Add durable failure records in all `process_order_event` failure exits.
2. Add canonical order status transitions and enforce them.
3. Add attachment-level idempotency in processing.

P1:

1. Standardize logging usage across modules.
2. Add emulator integration tests for status/idempotency/firestore writes.
3. Implement Inbox page with status filters.

P2:

1. Add golden extraction regression suite.
2. Add supplier analytics and prompt sandbox UI.
3. Harden deployment security defaults (remove unnecessary unauthenticated endpoints where possible).
