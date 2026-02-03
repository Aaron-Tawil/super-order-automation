from google.cloud import storage
import os
import uuid

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "super-home-automation-raw")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")

def upload_to_gcs(file_path: str, original_filename: str) -> str:
    """
    Uploads a file to GCS and returns the public URL or gs:// URI.
    Includes retry logic for network and SSL errors.
    """
    import time
    from google.api_core import retry as api_retry
    max_retries = 3
    timeout = 300  # 5 minutes
    
    # Check file size for logging
    try:
        file_size = os.path.getsize(file_path) / 1024
        print(f"Preparing to upload {original_filename} ({file_size:.1f} KB) to GCS...")
    except:
        pass

    for attempt in range(max_retries):
        try:
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(BUCKET_NAME)
            
            # Generate unique name
            unique_name = f"{uuid.uuid4()}_{original_filename}"
            blob = bucket.blob(unique_name)
            
            # Use increased timeout AND explicit retry deadline
            # The 'deadline' in Retry object is what was hitting the 120s limit
            blob.upload_from_filename(
                file_path, 
                timeout=timeout, 
                retry=api_retry.Retry(deadline=timeout)
            )
            
            print(f"Uploaded {original_filename} to GS://{BUCKET_NAME}/{unique_name}")
            return f"gs://{BUCKET_NAME}/{unique_name}"
        
        except Exception as e:
            error_str = str(e)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"GCS upload attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Failed to upload to GCS after {max_retries} attempts: {e}")
                return None

def download_file_from_gcs(gcs_uri: str, local_path: str) -> bool:
    """
    Downloads a file from GCS to a local path.
    Args:
        gcs_uri: gs://bucket-name/blob-name
        local_path: Destination local path
    Returns:
        True if successful, False otherwise.
    """
    try:
        # Parse URI
        if not gcs_uri.startswith("gs://"):
            print("Invalid GCS URI")
            return False
            
        parts = gcs_uri.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1]
        
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        blob.download_to_filename(local_path)
        print(f"Downloaded {gcs_uri} to {local_path}")
        return True
    
    except Exception as e:
        print(f"Failed to download from GCS: {e}")
        return False
