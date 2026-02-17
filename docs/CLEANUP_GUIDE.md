# Cleanup Guide: Artifact Registry & Cloud Run

To clean up stale images and revisions, use the provided script.

## 1. The Script
Located at: `scripts/cleanup_artifacts.sh`

### What it does:
- Lists all **Cloud Run revisions** that are no longer serving traffic and deletes them.
- Lists all **GCR images** (`gcr.io/super-home-automation/order-dashboard`), keeps the **latest 5**, and deletes the rest.

## 2. Usage
Run the script from the project root:

```bash
./scripts/cleanup_artifacts.sh
```

## 3. Manual Commands (Reference)
If you prefer running commands manually:

### Revisions
```bash
# List revisions to review
gcloud run revisions list --service order-dashboard

# Delete a specific revision
gcloud run revisions delete [REVISION_NAME] --region us-central1
```

### Images
```bash
# List images by date
gcloud container images list-tags gcr.io/super-home-automation/order-dashboard --sort-by=~TIMESTAMP

# Delete an image by digest
gcloud container images delete gcr.io/super-home-automation/order-dashboard@sha256:[DIGEST]
```
