---
trigger: always_on
---

when it is time to deploy only present to me the commands needed for the deploy and i will run it myself. add the flags for the deploy script

NOTE: The project now uses `uv` for dependency management, but Cloud Functions and Cloud Run builds still rely on `requirements.txt`.
ALWAYS instruct the user to update `requirements.txt` from `uv.lock` before deploying.

Required Deployment Steps:

1. **Sync dependencies**:
   ```bash
   uv export --format requirements-txt > requirements.txt
   ```

2. **Deploy Backend (Cloud Functions)**:
   ```bash
   python deploy.py
   ```
   (Flags: `--skip-secret`, `--skip-watch`, `--skip-renew-watch` if needed)

3. **Deploy Frontend (Cloud Run)**:
   ```bash
   python deploy_ui.py
   ```
   OR
   ```bash
   gcloud builds submit --config=cloudbuild.yaml --project=super-home-automation
   ```