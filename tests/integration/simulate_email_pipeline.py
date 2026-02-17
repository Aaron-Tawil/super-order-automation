#!/usr/bin/env python3
"""
Simulate Email Pipeline Integration Test

This script simulates the entire flow of an email arriving:
1. Uploads a local file to GCS (mimicking Ingestion Service).
2. Constructs an OrderIngestedEvent (mimicking Pub/Sub payload).
3. Calls process_order_event directly (mimicking Cloud Function trigger).

Usage:
    python tests/integration/simulate_email_pipeline.py --file path/to/invoice.pdf
"""

import argparse
import base64
import json
import logging
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.events import EmailMetadata, OrderIngestedEvent
from src.functions.processor_fn import process_order_event
from src.ingestion.gcs_writer import upload_to_gcs
from src.shared.config import settings
from src.shared.logger import get_logger

# Configure logger to print to console
logging.basicConfig(level=logging.INFO)
logger = get_logger(__name__)


def create_mock_cloud_event(event_model: OrderIngestedEvent):
    """
    Wraps the event model in a mock CloudEvent object compatible with functions-framework.
    """
    # Serialize event to JSON
    json_data = event_model.model_dump_json()

    # Pub/Sub payload is base64 encoded
    data_b64 = base64.b64encode(json_data.encode("utf-8")).decode("utf-8")

    # Mock CloudEvent
    mock_event = MagicMock()
    mock_event.data = {"message": {"data": data_b64}}
    mock_event.id = f"evt_{int(datetime.utcnow().timestamp())}"
    return mock_event


def run_simulation(file_path):
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    logger.info(f"--- Starting Simulation for {file_path} ---")

    # 1. Simulating Ingestion (Upload to GCS)
    filename = os.path.basename(file_path)
    logger.info("Step 1: Uploading file to GCS...")
    try:
        gcs_uri = upload_to_gcs(file_path, filename)
        if not gcs_uri:
            logger.error("Upload failed.")
            return
        logger.info(f"Upload successful: {gcs_uri}")
    except Exception as e:
        logger.error(f"Upload failed with error: {e}")
        return

    # 2. Construct Event
    logger.info("Step 2: Constructing OrderIngestedEvent...")
    email_meta = EmailMetadata(
        message_id="sim_msg_001",
        thread_id="sim_thread_001",
        sender="simulation@localhost",
        subject=f"Simulation Invoice {filename}",
        received_at=datetime.utcnow(),
        body_snippet="This is a simulated email body for testing purposes.",
    )

    # Determine mime type
    mime_type = "application/pdf"
    if filename.lower().endswith(".xlsx"):
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    event = OrderIngestedEvent(
        gcs_uri=gcs_uri,
        bucket_name=settings.GCS_BUCKET_NAME,
        blob_name=gcs_uri.replace(f"gs://{settings.GCS_BUCKET_NAME}/", ""),
        filename=filename,
        mime_type=mime_type,
        email_metadata=email_meta,
    )

    # Wrap in CloudEvent
    cloud_event = create_mock_cloud_event(event)

    # 3. Trigger Processing Function
    logger.info("Step 3: Triggering process_order_event (Cloud Function)...")
    try:
        # This calls the actual function which will:
        # - Download file from GCS
        # - Call OrderProcessor (Vertex AI)
        # - Save to Firestore
        process_order_event(cloud_event)
        logger.info("--- Simulation Completed Successfully ---")
        logger.info("Check Firestore and Logs for details.")
    except Exception as e:
        logger.error(f"Simulation failed during processing: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate Email Pipeline")
    parser.add_argument("--file", required=True, help="Path to local invoice file")
    args = parser.parse_args()

    run_simulation(args.file)
