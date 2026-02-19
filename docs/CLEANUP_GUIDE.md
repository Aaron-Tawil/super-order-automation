# Artifact Cleanup Guide

The `scripts/cleanup_artifacts.sh` script helps manage storage costs and clutter by removing old Cloud Run revisions and container images.

## Features
- **Cloud Run Revisions**: Deletes all **inactive** revisions for:
    - `order-dashboard` (Cloud Run Service)
    - `order-bot` (Cloud Function Gen 2)
    - `process-order-event` (Cloud Function Gen 2)
    - `renew-watch-orders` (Cloud Function Gen 2)
- **Container Images**: Keeps only the **latest 5 images** for each service, deleting older ones.
    - Cleans GCR images (`gcr.io`) for the dashboard.
    - Cleans Artifact Registry images (`us-central1-docker.pkg.dev`) for Cloud Functions.

## Usage

Simply run the script from the project root:

```bash
./scripts/cleanup_artifacts.sh
```

## How it Works

1.  **Revisions**: It lists all revisions for each service. It filters for `status.conditions.type=Active` and `status.conditions.status=False` (meaning inactive/not serving traffic) and deletes them.
2.  **Images**: It lists all image digests sorted by date. It skips the most recent 5 and deletes the rest.

## Configuration

You can modify the following variables at the top of the script:
- `PROJECT_ID`: Your Google Cloud Project ID.
- `REGION`: The region (default: `us-central1`).
- `KEEP_COUNT`: Number of recent images to keep (default: `5`).
