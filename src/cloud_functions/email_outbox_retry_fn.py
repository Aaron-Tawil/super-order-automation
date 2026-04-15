import functions_framework

from src.data.email_outbox_service import EmailOutboxService
from src.ingestion.email_outbox_sender import OUTBOX_SEND_PERMANENT_FAILED, OUTBOX_SEND_SENT, send_outbox_email
from src.ingestion.gmail_utils import get_gmail_service
from src.shared.logger import get_logger

logger = get_logger(__name__)


def retry_pending_outbox_emails(limit: int = 50) -> dict:
    """Retry due user-facing response emails from the durable outbox."""
    service = EmailOutboxService()
    emails = service.list_due_emails(limit=limit)
    if not emails:
        return {"checked": 0, "sent": 0, "failed": 0, "permanent_failed": 0, "waiting": 0}

    gmail_service = get_gmail_service()
    if not gmail_service:
        for email in emails:
            service.mark_waiting(str(email.get("outbox_id")), last_error="Gmail service unavailable")
        return {
            "checked": len(emails),
            "sent": 0,
            "failed": 0,
            "permanent_failed": 0,
            "waiting": len(emails),
            "service_unavailable": True,
        }

    sent_count = 0
    failed_count = 0
    permanent_failed_count = 0

    for email in emails:
        outbox_id = str(email.get("outbox_id"))
        attempts = int(email.get("attempt_count") or 0) + 1
        send_status, error = send_outbox_email(email, gmail_service)
        if send_status == OUTBOX_SEND_SENT:
            sent_count += 1
            service.mark_sent(outbox_id, attempts=attempts)
            continue

        if send_status == OUTBOX_SEND_PERMANENT_FAILED:
            permanent_failed_count += 1
            service.mark_failed_permanent(outbox_id, attempts=attempts, last_error=error)
            continue

        failed_count += 1
        service.mark_retry(outbox_id, attempts=attempts, last_error=error or "Email send failed")

    return {
        "checked": len(emails),
        "sent": sent_count,
        "failed": failed_count + permanent_failed_count,
        "permanent_failed": permanent_failed_count,
        "waiting": 0,
    }


@functions_framework.http
def retry_email_outbox(request):
    try:
        result = retry_pending_outbox_emails()
        logger.info(f"Email outbox retry result: {result}")
        return result, 200
    except Exception as e:
        logger.error(f"Error retrying email outbox: {e}", exc_info=True)
        return {"error": str(e)}, 500
