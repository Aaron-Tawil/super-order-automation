# cleanup_artifacts.ps1
# PowerShell equivalent of cleanup_artifacts.sh

$ProjectID = "super-home-automation"
$Region = "us-central1"
$KeepCount = 5

$Services = @(
    "order-dashboard",
    "order-bot",
    "process-order-event",
    "renew-watch-orders"
)

Write-Host "Starting Cleanup for Project: $ProjectID"
Write-Host "Keeping latest $KeepCount versions..."

function Clean-Revisions {
    param($ServiceName)
    Write-Host ""
    Write-Host "--- [$ServiceName] Cleanup Cloud Run Revisions ---"
    
    # Check if service exists
    $describe = gcloud run services describe $ServiceName --project=$ProjectID --region=$Region 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Service $ServiceName not found (or not a Cloud Run service). Skipping revisions."
        return
    }

    # List inactive revisions
    $revisions = gcloud run revisions list `
        --service=$ServiceName `
        --project=$ProjectID `
        --region=$Region `
        --filter="status.conditions.type=Active AND status.conditions.status=False" `
        --format="value(name)"

    if ($revisions) {
        $revisionsList = $revisions -split "`r`n" | Where-Object { $_ -ne "" }
        Write-Host "Found $($revisionsList.Count) inactive revisions for $ServiceName."
        foreach ($rev in $revisionsList) {
            Write-Host "Deleting revision: $rev"
            gcloud run revisions delete $rev --region=$Region --project=$ProjectID --quiet
        }
        Write-Host "Deleted inactive revisions."
    } else {
        Write-Host "No inactive revisions found."
    }
}

function Clean-GCRImages {
    param($ImageName)
    Write-Host ""
    Write-Host "--- [$ImageName] Cleanup GCR Images ---"

    $digests = gcloud container images list-tags $ImageName `
        --limit=9999 `
        --sort-by=~TIMESTAMP `
        --format="get(digest)" 2>$null

    if ($digests) {
        $digestsList = $digests -split "`r`n" | Where-Object { $_ -ne "" }
        if ($digestsList.Count -gt $KeepCount) {
            $toDelete = $digestsList | Select-Object -Skip $KeepCount
            Write-Host "Found $($toDelete.Count) old images to delete."
            foreach ($digest in $toDelete) {
                Write-Host "Deleting $ImageName@$digest ..."
                gcloud container images delete "$ImageName@$digest" --force-delete-tags --quiet
            }
            Write-Host "Deleted old images."
        } else {
            Write-Host "No old images found to delete (Count: $($digestsList.Count) <= $KeepCount)."
        }
    } else {
        Write-Host "No images found for $ImageName."
    }
}

function Clean-ARImages {
    param($ServiceName)
    $Repo = "us-central1-docker.pkg.dev/$ProjectID/gcf-artifacts"
    $ImageName = "$Repo/$ServiceName"
    
    Write-Host ""
    Write-Host "--- [$ServiceName] Cleanup Artifact Registry Images ---"
    
    $digests = gcloud artifacts docker images list $ImageName `
        --include-tags `
        --sort-by=~UPDATE_TIME `
        --format="value(digest)" 2>$null

    if ($digests) {
        $digestsList = $digests -split "`r`n" | Where-Object { $_ -ne "" } | Select-Object -Unique
        if ($digestsList.Count -gt $KeepCount) {
            $toDelete = $digestsList | Select-Object -Skip $KeepCount
            Write-Host "Found $($toDelete.Count) old images to delete."
            foreach ($digest in $toDelete) {
                Write-Host "Deleting $ImageName@$digest ..."
                gcloud artifacts docker images delete "$ImageName@$digest" --delete-tags --quiet
            }
            Write-Host "Deleted old images."
        } else {
            Write-Host "No old images found to delete (Count: $($digestsList.Count) <= $KeepCount)."
        }
    } else {
        Write-Host "No images found for $ImageName in Artifact Registry."
    }
}

# Main Loop
foreach ($Service in $Services) {
    Clean-Revisions -ServiceName $Service
    
    if ($Service -eq "order-dashboard") {
        Clean-GCRImages -ImageName "gcr.io/$ProjectID/$Service"
    } else {
        Clean-ARImages -ServiceName $Service
    }
}

Write-Host ""
Write-Host "Global Cleanup Complete!"
