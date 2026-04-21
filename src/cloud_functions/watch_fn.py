import functions_framework

from src.shared.logger import get_logger

logger = get_logger(__name__)


@functions_framework.http
def renew_watch(request):
    """
    HTTP Cloud Function to renew Gmail Watch.
    Triggered by Cloud Scheduler daily.
    """
    try:
        from src.ingestion.gmail_utils import get_gmail_service
        from src.ingestion.gmail_watch import setup_watch

        logger.info("Starting Gmail Watch renewal...")

        service = get_gmail_service()
        if not service:
            logger.error("Failed to obtain Gmail service.")
            return "Failed to obtain Gmail service", 500

        response = setup_watch(service=service)
        logger.info(f"Watch renewal response: {response}")

        return f"Watch renewed successfully: {response}", 200

    except Exception as e:
        logger.error(f"Error renewing watch: {e}", exc_info=True)
        return f"Error renewing watch: {e}", 500
