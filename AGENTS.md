# Repository Guidelines

## Project Structure & Module Organization
Core application code lives under `src/`:
- `src/ingestion`: Gmail ingestion and attachment handling
- `src/extraction`: local supplier detection, Gemini prompts/schemas, and model client logic
- `src/core`: processing pipeline, validation, and domain rules
- `src/data`: Firestore-backed service layers
- `src/export`: Excel generation
- `src/dashboard`: Streamlit UI, OAuth auth flow, inbox, and order editing flows
- `src/cloud_functions`: Cloud Function entry points
- `src/shared`: config, models, logging, and shared utilities

Tests are in `tests/` (plus integration helpers in `tests/integration/`). Operational scripts are in `scripts/`. Docs and maintenance notes are in `docs/`. Deployment entrypoints are [`deploy.py`](/mnt/c/Dev/super-order-automation/deploy.py), [`deploy_ui.py`](/mnt/c/Dev/super-order-automation/deploy_ui.py), and [`main.py`](/mnt/c/Dev/super-order-automation/main.py) for Cloud Function entrypoint imports.

## Build, Test, and Development Commands
- `uv sync --dev`: install runtime and dev dependencies.
- `uv run streamlit run src/dashboard/app.py`: run UI locally.
- `uv run pytest`: run the full test suite.
- `uv run pytest tests/test_processor_fn.py -q`: run a focused test file.
- `uv run ruff check .`: run lint rules.
- `uv run ruff format .`: format code.
- `uv run pre-commit run --all-files`: run repo hooks before pushing.
- `uv export --format requirements-txt > requirements.txt`: refresh deployable requirements after dependency changes.

## Coding Style & Naming Conventions
Use Python 3.11+, 4-space indentation, and double quotes (Ruff formatter default). Follow snake_case for modules/functions/variables, PascalCase for classes, and `UP`-compatible modern Python syntax where practical. Keep imports ordered (Ruff/isort rules). Place new domain logic in the closest existing `src/*` module rather than creating parallel folders.

## Testing Guidelines
Framework: `pytest` with fixtures in [`tests/conftest.py`](/mnt/c/Dev/super-order-automation/tests/conftest.py). Name tests `test_*.py` and test functions `test_<behavior>()`. Add unit tests for processing, extraction, and validation changes; include integration-style coverage when touching ingestion/event flows. No explicit coverage threshold is enforced, but PRs should include meaningful regression tests.

When touching dashboard auth/session behavior, prefer updating or adding coverage in [`tests/test_dashboard_auth.py`](/mnt/c/Dev/super-order-automation/tests/test_dashboard_auth.py), [`tests/test_frontend.py`](/mnt/c/Dev/super-order-automation/tests/test_frontend.py), and [`tests/test_order_session.py`](/mnt/c/Dev/super-order-automation/tests/test_order_session.py). For ingestion and processor changes, start with [`tests/test_ingestion_service.py`](/mnt/c/Dev/super-order-automation/tests/test_ingestion_service.py) and [`tests/test_processor_fn.py`](/mnt/c/Dev/super-order-automation/tests/test_processor_fn.py).

## Commit & Pull Request Guidelines
Recent history favors short, imperative subjects, often with conventional prefixes (`feat:`, `fix:`, `refactor:`, `minor:`). Use `<type>: <summary>` where possible, e.g. `fix: handle missing VAT in processor`.

For PRs, include:
- clear scope and impacted modules
- linked issue/task (if available)
- test evidence (`uv run pytest` output summary)
- UI screenshots for `src/dashboard` changes
- deployment notes when `requirements.txt`, Cloud Functions, or Cloud Run behavior changes

## Security & Configuration Tips
Keep secrets in `.env` or Secret Manager; do not commit credentials or tokens. Validate required env vars before running cloud flows. The dashboard currently supports Google and Microsoft OAuth plus `ALLOWED_EMAILS` allowlisting, so auth-related changes should be reflected in `.env.example` and tested locally. If dependencies change, update `requirements.txt` before `deploy.py`/`deploy_ui.py` so cloud builds match local code.
