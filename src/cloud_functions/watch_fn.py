import logging

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)

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
