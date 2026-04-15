import functions_framework

from src.cloud_functions.email_outbox_retry_fn import retry_pending_outbox_emails


@functions_framework.http
def retry_failed_feedback_emails(request):
    """Backward-compatible entry point; retries the generic email outbox."""
    result = retry_pending_outbox_emails()
    return result, 200
