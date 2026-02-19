#!/bin/bash
# cleanup_artifacts.sh

# Configuration
PROJECT_ID="super-home-automation"
REGION="us-central1"
KEEP_COUNT=5

# Defined Services (Cloud Run & Functions)
# Note: Cloud Functions Gen 2 appear as Cloud Run services
SERVICES=(
    "order-dashboard"
    "order-bot"
    "process-order-event"
    "renew-watch-orders"
)

echo "Starting Cleanup for Project: $PROJECT_ID"
echo "Keeping latest $KEEP_COUNT versions..."

# Function to clean Cloud Run Revisions
clean_revisions() {
    local SERVICE_NAME=$1
    echo ""
    echo "--- [$SERVICE_NAME] Cleanup Cloud Run Revisions ---"
    
    # Check if service exists first to avoid errors
    if ! gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
        echo "Service $SERVICE_NAME not found (or not a Cloud Run service). Skipping revisions."
        return
    fi

    # List inactive revisions
    gcloud run revisions list \
        --service="$SERVICE_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --filter="status.conditions.type=Active AND status.conditions.status=False" \
        --format="value(name)" > revisions_to_delete.txt

    if [ -s revisions_to_delete.txt ]; then
        local count=$(wc -l < revisions_to_delete.txt)
        echo "Found $count inactive revisions for $SERVICE_NAME."
        # Delete them
        cat revisions_to_delete.txt | \
        xargs -I {} gcloud run revisions delete {} --region="$REGION" --project="$PROJECT_ID" --quiet
        echo "Deleted inactive revisions."
    else
        echo "No inactive revisions found."
    fi
    rm -f revisions_to_delete.txt
}

# Function to clean GCR Images (for order-dashboard)
clean_gcr_images() {
    local IMAGE_NAME=$1
    echo ""
    echo "--- [$IMAGE_NAME] Cleanup GCR Images ---"

    # List digests by date, skip latest N
    gcloud container images list-tags "$IMAGE_NAME" \
        --limit=9999 \
        --sort-by=~TIMESTAMP \
        --format="get(digest)" 2>/dev/null | tail -n +$((KEEP_COUNT + 1)) > images_to_delete.txt

    if [ -s images_to_delete.txt ]; then
        local count=$(wc -l < images_to_delete.txt)
        echo "Found $count old images to delete."
        while read -r digest; do
            echo "Deleting $IMAGE_NAME@$digest ..."
            gcloud container images delete "$IMAGE_NAME@$digest" --force-delete-tags --quiet
        done < images_to_delete.txt
        echo "Deleted old images."
    else
        echo "No old images found to delete."
    fi
    rm -f images_to_delete.txt
}

# Function to clean Artifact Registry Images (for Cloud Functions)
clean_ar_images() {
    local REPO="us-central1-docker.pkg.dev/$PROJECT_ID/gcf-artifacts"
    local IMAGE_NAME="$REPO/$1"
    
    echo ""
    echo "--- [$1] Cleanup Artifact Registry Images ---"
    
    # List digests by create time, skip latest N
    # Note: Artifact Registry commands might differ slightly in output format/sorting
    # We use 'artifacts docker images list'
    
    gcloud artifacts docker images list "$IMAGE_NAME" \
        --include-tags \
        --sort-by=~UPDATE_TIME \
        --format="value(digest)" 2>/dev/null | tail -n +$((KEEP_COUNT + 1)) > images_to_delete.txt
        
    if [ -s images_to_delete.txt ]; then
        local count=$(wc -l < images_to_delete.txt)
        echo "Found $count old images to delete."
        while read -r digest; do
            echo "Deleting $IMAGE_NAME@$digest ..."
            gcloud artifacts docker images delete "$IMAGE_NAME@$digest" --delete-tags --quiet
        done < images_to_delete.txt
        echo "Deleted old images."
    else
        echo "No old images found to delete."
    fi
    rm -f images_to_delete.txt
}


# Main Loop
for SERVICE in "${SERVICES[@]}"; do
    clean_revisions "$SERVICE"
    
    if [ "$SERVICE" == "order-dashboard" ]; then
        # Check if using GCR or AR (Dashboard configured for GCR in script)
        clean_gcr_images "gcr.io/$PROJECT_ID/$SERVICE"
    else
        # Functions use Artifact Registry
        clean_ar_images "$SERVICE"
    fi
done

echo ""
echo "Global Cleanup Complete!"
