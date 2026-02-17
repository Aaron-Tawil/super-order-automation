# Deployment Guide

This project is split into two cloud services:
1.  **Order Bot**: A Cloud Function that processes incoming emails (`src/ingestion`, `src/extraction`).
2.  **Dashboard UI**: A Cloud Run service that hosts the web interface (`src/dashboard`).

## Prerequisites

**Dependencies (Important):**
The project uses `uv` for local dependency management, but Cloud Functions and Cloud Run builds rely on `requirements.txt`.
**Before ANY deployment**, you must sync `requirements.txt` with your `uv` environment:

```bash
uv export --format requirements-txt > requirements.txt
```

---

## Quick Reference

| If you edited... | Run these commands |
| :--- | :--- |
| **Email Logic / Extraction** (`src/ingestion`, `src/extraction`) | 1. `uv export --format requirements-txt > requirements.txt`<br>2. `python deploy.py` |
| **User Interface** (`src/dashboard`) | 1. `uv export --format requirements-txt > requirements.txt`<br>2. `python deploy_ui.py` |
| **Shared Models / Logic** (`src/shared`) | **Run ALL** commands above (update requirements, then deploy Bot + UI) |

---

## Detailed Instructions

### 1. Deploying the Email Bot
Run this when you change how emails are processed, how data is extracted, or database logic.

```bash
# 1. Update requirements (if you added/removed packages)
uv export --format requirements-txt > requirements.txt

# 2. Deploy
python deploy.py
```

*   **What it does**: Deploys the `order-bot` Cloud Function.
*   **Options**:
    *   `--skip-secret`: Skips updating the Gmail token in Secret Manager (faster if you didn't change the token).
    *   `--skip-watch`: Skips renewing the Gmail watch (useful for quick code updates).
    *   `--skip-renew-watch`: Skips renewing the `renew-watch-orders` function.

> **Note on Upload Speed**: We use a `.gcloudignore` file to exclude unnecessary files (like `.venv`, `tests-data`, etc.) from the upload. This keeps deployments fast.

### 2. Deploying the Dashboard UI
Run this when you change the Streamlit app, layout, or UI logic.

```bash
# 1. Update requirements (if you added/removed packages with uv)
uv export --format requirements-txt > requirements.txt

# 2. Deploy
python deploy_ui.py
# OR manually: gcloud builds submit --config=cloudbuild.yaml --project=super-home-automation
```

*   **What it does**:
    1.  Builds a new Docker container using Cloud Build.
    2.  Pushes the image to Google Container Registry (GCR).
    3.  Deploys the new image to Cloud Run.

> **Note on Build Speed**: We use a `.dockerignore` file to exclude the local `.venv`, `.git`, and other heavy directories from the Docker build context. This speeds up the upload significantly (from ~1.2GB down to ~400KB).

### 3. Updating Configuration (.env)
If you change environment variables in `.env`:
1.  **For the Bot**: Run `python deploy.py` (it reloads env vars on deploy).
2.  **For the UI**: `deploy_ui.py` currently sets specific variables in the `gcloud run deploy` command. If you added new variables, you might need to edit `deploy_ui.py` to include them.

### Troubleshooting
*   **"Module not found" in Cloud logs**: Did you remember to run `uv export ...` before deploying? The Cloud environment only knows about packages listed in `requirements.txt`.
*   **Cloud Build Fails**: Check `.gcloudignore` / `.dockerignore` and ensure all necessary source files are included.
*   **Verification**:
    *   **Bot**: Send a test email.
    *   **UI**: Visit the URL printed at the end of the `deploy_ui.py` script.
