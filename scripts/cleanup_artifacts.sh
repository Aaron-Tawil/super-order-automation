#!/bin/bash
# cleanup_artifacts.sh

# Configuration
PROJECT_ID="super-home-automation"
IMAGE_NAME="gcr.io/$PROJECT_ID/order-dashboard"
SERVICE_NAME="order-dashboard"
REGION="us-central1"
KEEP_COUNT=5

echo "Starting Cleanup for Project: $PROJECT_ID"
echo "Image: $IMAGE_NAME"
echo "Service: $SERVICE_NAME"
echo "Keeping latest $KEEP_COUNT versions..."

# 1. Cleanup Old Cloud Run Revisions (Keep latest serving ones)
echo ""
echo "--- Cleanup Cloud Run Revisions ---"
# Get all revisions sorted by creation time (oldest first) excluding latest serving ones
# This is tricky with plain gcloud, simpler to delete non-serving revisions.
# List all non-serving revisions
gcloud run revisions list \
    --service="$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --filter="status.conditions.type=Active AND status.conditions.status=False" \
    --format="value(name)" > revisions_to_delete.txt

if [ -s revisions_to_delete.txt ]; then
    count=$(wc -l < revisions_to_delete.txt)
    echo "Found $count inactive revisions to delete."
    # Delete them
    cat revisions_to_delete.txt | \
    xargs -I {} gcloud run revisions delete {} --region="$REGION" --project="$PROJECT_ID" --quiet
    echo "Deleted inactive revisions."
else
    echo "No inactive revisions found."
fi
rm revisions_to_delete.txt


# 2. Cleanup Old Images (Keep latest N)
echo ""
echo "--- Cleanup GCR Images ---"
# List all image digests by date, excluding latest N
gcloud container images list-tags "$IMAGE_NAME" \
    --limit=9999 \
    --sort-by=~TIMESTAMP \
    --format="get(digest)" | tail -n +$((KEEP_COUNT + 1)) > images_to_delete.txt

if [ -s images_to_delete.txt ]; then
    count=$(wc -l < images_to_delete.txt)
    echo "Found $count old images to delete."
    # Construct full image reference with digest
    while read -r digest; do
        echo "Deleting $IMAGE_NAME@$digest ..."
        gcloud container images delete "$IMAGE_NAME@$digest" --force-delete-tags --quiet
    done < images_to_delete.txt
    echo "Deleted old images."
else
    echo "No old images to delete (found fewer than $KEEP_COUNT total)."
fi
rm images_to_delete.txt

echo ""
echo "Cleanup Complete!"
