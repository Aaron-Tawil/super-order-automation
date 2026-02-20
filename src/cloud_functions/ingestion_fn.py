import logging

import functions_framework

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
