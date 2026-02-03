# Deployment Guide

This project is split into two cloud services:
1.  **Order Bot**: A Cloud Function that processes incoming emails (`src/ingestion`, `src/extraction`).
2.  **Dashboard UI**: A Cloud Run service that hosts the web interface (`src/dashboard`).

## Quick Reference

| If you edited... | Run this command |
| :--- | :--- |
| **Email Logic / Extraction** (`src/ingestion`, `src/extraction`) | `python deploy.py` |
| **User Interface** (`src/dashboard`) | `python deploy_ui.py` |
| **Shared Models / Logic** (`src/shared`) | **Run BOTH** commands above |

---

## detailed Instructions

### 1. Deploying the Email Bot
Run this when you change how emails are processed, how data is extracted, or database logic.
```bash
python deploy.py
*   **What it does**: Deploys the `order-bot` Cloud Function.
*   **Options**:
    *   `--skip-secret`: Skips updating the Gmail token in Secret Manager (faster if you didn't change the token).
    *   `--skip-watch`: Skips renewing the Gmail watch (useful for quick code updates).
    *   `--skip-renew-watch`: Skips renewing the Gmail watch (useful for quick code updates).
    

### 2. Deploying the Dashboard UI
Run this when you change the Streamlit app, layout, or UI logic.
python deploy_ui.py
```
*   **What it does**:
    1.  Builds a new Docker container using Cloud Build.
    2.  Pushes the image to Google Container Registry (GCR).
    3.  Deploys the new image to Cloud Run.

### 3. Updating Configuration (.env)
If you change environment variables in `.env`:
1.  **For the Bot**: Run `python deploy.py` (it reloads env vars on deploy).
2.  **For the UI**: `deploy_ui.py` currently sets specific variables in the `gcloud run deploy` command. If you added new variables, you might need to edit `deploy_ui.py` to include them.

### Troubleshooting
*   **Cloud Build Fails**: Check `.gcloudignore` and ensure all necessary files are included (not ignored).
*   **Verification**:
    *   **Bot**: Send a test email.
    *   **UI**: Visit the URL printed at the end of the `deploy_ui.py` script.
