import os
import time
import uuid

from google.api_core import retry as api_retry
from google.cloud import storage

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


def upload_to_gcs(file_path: str, original_filename: str) -> str:
    """
    Uploads a file to GCS and returns the public URL or gs:// URI.
    Includes retry logic for network and SSL errors.
    """
    bucket_name = settings.GCS_BUCKET_NAME
    max_retries = 3
    timeout = 300  # 5 minutes

    # Check file size for logging
    try:
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path) / 1024
            logger.info(f"Preparing to upload {original_filename} ({file_size:.1f} KB) to GCS...")
        else:
            logger.error(f"File not found for upload: {file_path}")
            return None
    except Exception:
        pass

    for attempt in range(max_retries):
        try:
            client = storage.Client(project=settings.PROJECT_ID)
            bucket = client.bucket(bucket_name)

            # Generate unique name
            safe_filename = "".join([c for c in original_filename if c.isalnum() or c in ('-', '_', '.')]).strip()
            unique_name = f"{uuid.uuid4()}_{safe_filename}"
            blob = bucket.blob(unique_name)

            # Use increased timeout AND explicit retry deadline
            blob.upload_from_filename(file_path, timeout=timeout, retry=api_retry.Retry(deadline=timeout))

            logger.info(f"File {original_filename} uploaded to {bucket_name}/{unique_name}")
            return f"gs://{bucket_name}/{unique_name}"

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                logger.warning(f"GCS upload attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to upload to GCS after {max_retries} attempts: {e}")
                return None


def download_file_from_gcs(gcs_uri: str, destination_file_path: str) -> bool:
    """
    Downloads a file from GCS URI (gs://bucket/blob) to local path.
    """
    try:
        if not gcs_uri.startswith("gs://"):
            logger.error(f"Invalid GCS URI: {gcs_uri}")
            return False

        parts = gcs_uri[5:].split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1]

        storage_client = storage.Client(project=settings.PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        blob.download_to_filename(destination_file_path)
        logger.info(f"Downloaded {gcs_uri} to {destination_file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download from GCS: {e}")
        return False
