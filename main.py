import logging
import os
import sys
from typing import Any, Dict

import functions_framework

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.functions.processor_fn import process_order_event
from src.ingestion.email_processor import process_unread_emails

# Configure logging
logging.basicConfig(level=logging.INFO)


@functions_framework.cloud_event
def order_bot(cloud_event):
    """
    Cloud Function triggered by Pub/Sub for Gmail notifications.
    Payload (cloud_event.data) contains the Pub/Sub message.
    """
    try:
        logging.info(f"Received event: {cloud_event['id']}")

        # We don't necessarily need the message data itself
        # (it usually just says "something changed" or has a historyId).
        # We just need to trigger the inbox check.

        processed_count = process_unread_emails()
        logging.info(f"Processed {processed_count} emails.")

        return "OK"

    except Exception as e:
        # Log the error but return success to avoid infinite Pub/Sub retries
        # if it's a permanent error (like code bug).
        # For transient errors, you might want to raise Exception to trigger retry.
        logging.error(f"Error in Cloud Function: {e}", exc_info=True)
        return "Error handled"


@functions_framework.http
def renew_watch(request):
    """
    HTTP Cloud Function to renew Gmail Watch.
    Triggered by Cloud Scheduler daily.
    """
    try:
        from src.ingestion.gmail_utils import get_gmail_service
        from src.ingestion.gmail_watch import setup_watch

        logging.info("Starting Gmail Watch renewal...")

        service = get_gmail_service()
        if not service:
            logging.error("Failed to obtain Gmail service.")
            return "Failed to obtain Gmail service", 500

        response = setup_watch(service=service)
        logging.info(f"Watch renewal response: {response}")

        return f"Watch renewed successfully: {response}", 200

    except Exception as e:
        logging.error(f"Error renewing watch: {e}", exc_info=True)
        return f"Error renewing watch: {e}", 500
