from unittest.mock import MagicMock, patch

from src.cloud_functions.email_outbox_retry_fn import retry_pending_outbox_emails
from src.ingestion.email_outbox_sender import (
    OUTBOX_SEND_PERMANENT_FAILED,
    OUTBOX_SEND_RETRYABLE_FAILED,
    OUTBOX_SEND_SENT,
)


def _email(attempts=0, outbox_id="outbox-1"):
    return {
        "outbox_id": outbox_id,
        "event_id": "evt-1",
        "email_type": "SUCCESS",
        "attempt_count": attempts,
        "thread_id": "thread-1",
        "message_id": "msg-1",
        "to": "sender@example.com",
        "subject": "Invoice",
        "body": "hello",
        "attachment_refs": [],
    }


def test_retry_pending_outbox_emails_marks_sent():
    service = MagicMock()
    service.list_due_emails.return_value = [_email()]

    with (
        patch("src.cloud_functions.email_outbox_retry_fn.EmailOutboxService", return_value=service),
        patch("src.cloud_functions.email_outbox_retry_fn.get_gmail_service", return_value=MagicMock()),
        patch(
            "src.cloud_functions.email_outbox_retry_fn.send_outbox_email",
            return_value=(OUTBOX_SEND_SENT, None),
        ) as mock_send,
    ):
        result = retry_pending_outbox_emails()

    assert result == {"checked": 1, "sent": 1, "failed": 0, "permanent_failed": 0, "waiting": 0}
    mock_send.assert_called_once()
    service.mark_sent.assert_called_once_with("outbox-1", attempts=1)


def test_retry_pending_outbox_emails_marks_waiting_when_gmail_unavailable():
    service = MagicMock()
    service.list_due_emails.return_value = [_email()]

    with (
        patch("src.cloud_functions.email_outbox_retry_fn.EmailOutboxService", return_value=service),
        patch("src.cloud_functions.email_outbox_retry_fn.get_gmail_service", return_value=None),
        patch("src.cloud_functions.email_outbox_retry_fn.send_outbox_email") as mock_send,
    ):
        result = retry_pending_outbox_emails()

    assert result == {
        "checked": 1,
        "sent": 0,
        "failed": 0,
        "permanent_failed": 0,
        "waiting": 1,
        "service_unavailable": True,
    }
    mock_send.assert_not_called()
    service.mark_waiting.assert_called_once_with("outbox-1", last_error="Gmail service unavailable")


def test_retry_pending_outbox_emails_marks_retry_on_send_failure():
    service = MagicMock()
    service.list_due_emails.return_value = [_email(attempts=4)]

    with (
        patch("src.cloud_functions.email_outbox_retry_fn.EmailOutboxService", return_value=service),
        patch("src.cloud_functions.email_outbox_retry_fn.get_gmail_service", return_value=MagicMock()),
        patch(
            "src.cloud_functions.email_outbox_retry_fn.send_outbox_email",
            return_value=(OUTBOX_SEND_RETRYABLE_FAILED, "boom"),
        ),
    ):
        result = retry_pending_outbox_emails()

    assert result == {"checked": 1, "sent": 0, "failed": 1, "permanent_failed": 0, "waiting": 0}
    service.mark_retry.assert_called_once_with("outbox-1", attempts=5, last_error="boom")


def test_retry_pending_outbox_emails_marks_permanent_failure():
    service = MagicMock()
    service.list_due_emails.return_value = [_email(attempts=1)]

    with (
        patch("src.cloud_functions.email_outbox_retry_fn.EmailOutboxService", return_value=service),
        patch("src.cloud_functions.email_outbox_retry_fn.get_gmail_service", return_value=MagicMock()),
        patch(
            "src.cloud_functions.email_outbox_retry_fn.send_outbox_email",
            return_value=(OUTBOX_SEND_PERMANENT_FAILED, "missing thread"),
        ),
    ):
        result = retry_pending_outbox_emails()

    assert result == {"checked": 1, "sent": 0, "failed": 1, "permanent_failed": 1, "waiting": 0}
    service.mark_failed_permanent.assert_called_once_with("outbox-1", attempts=2, last_error="missing thread")
    service.mark_retry.assert_not_called()
