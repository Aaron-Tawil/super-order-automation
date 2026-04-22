from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from google.cloud import firestore

from src.data.email_outbox_service import (
    EMAIL_STATUS_FAILED_PERMANENT,
    EMAIL_STATUS_PENDING,
    EMAIL_STATUS_SENT,
    EmailOutboxService,
)


def _build_service():
    db = MagicMock()
    outbox_collection = MagicMock()
    orders_collection = MagicMock()
    processing_collection = MagicMock()
    db.collection.side_effect = [outbox_collection, orders_collection, processing_collection]
    service = EmailOutboxService(firestore_client=db)
    return service, outbox_collection, orders_collection, processing_collection


def _doc_snapshot(*, exists: bool, data: dict | None = None):
    snapshot = MagicMock()
    snapshot.exists = exists
    snapshot.to_dict.return_value = data or {}
    return snapshot


def test_list_due_emails_filters_due_before_limit():
    db = MagicMock()
    collection = db.collection.return_value
    status_query = collection.where.return_value
    due_query = status_query.where.return_value
    ordered_query = due_query.order_by.return_value
    limited_query = ordered_query.limit.return_value

    nowish = datetime.now(UTC) - timedelta(minutes=1)
    doc = MagicMock()
    doc.id = "outbox-1"
    doc.to_dict.return_value = {
        "status": EMAIL_STATUS_PENDING,
        "next_attempt_at": nowish,
        "event_id": "evt-1",
    }
    limited_query.stream.return_value = [doc]

    service = EmailOutboxService(firestore_client=db)
    emails = service.list_due_emails(limit=25)

    assert collection.where.call_args.kwargs["filter"] is not None
    assert status_query.where.call_args.kwargs["filter"] is not None
    due_query.order_by.assert_called_once_with("next_attempt_at", direction=firestore.Query.ASCENDING)
    ordered_query.limit.assert_called_once_with(25)
    assert emails == [
        {
            "status": EMAIL_STATUS_PENDING,
            "next_attempt_at": nowish,
            "event_id": "evt-1",
            "outbox_id": "outbox-1",
        }
    ]


def test_list_due_emails_falls_back_when_index_missing():
    db = MagicMock()
    collection = db.collection.return_value
    indexed_status_query = MagicMock()
    due_query = indexed_status_query.where.return_value
    ordered_query = due_query.order_by.return_value
    ordered_query.limit.return_value.stream.side_effect = Exception("The query requires an index")
    fallback_query = MagicMock()
    collection.where.side_effect = [indexed_status_query, fallback_query]

    due_at = datetime.now(UTC) - timedelta(minutes=1)
    future_at = datetime.now(UTC) + timedelta(minutes=30)
    due_doc = MagicMock()
    due_doc.id = "outbox-due"
    due_doc.to_dict.return_value = {"status": EMAIL_STATUS_PENDING, "next_attempt_at": due_at}
    future_doc = MagicMock()
    future_doc.id = "outbox-future"
    future_doc.to_dict.return_value = {"status": EMAIL_STATUS_PENDING, "next_attempt_at": future_at}
    fallback_query.stream.return_value = [future_doc, due_doc]

    service = EmailOutboxService(firestore_client=db)
    emails = service.list_due_emails(limit=10)

    assert [email["outbox_id"] for email in emails] == ["outbox-due"]


def test_enqueue_email_normalizes_blank_subject():
    service, outbox_collection, _orders_collection, _processing_collection = _build_service()
    doc_ref = MagicMock()
    doc_ref.get.return_value = _doc_snapshot(exists=False)
    outbox_collection.document.return_value = doc_ref

    outbox_id = service.enqueue_email(
        event_id="evt-1",
        email_type="success",
        thread_id="thread-1",
        message_id="msg-1",
        to="sender@example.com",
        subject="",
        body="hello",
    )

    assert outbox_id == "evt-1_success"
    assert doc_ref.set.call_args.args[0]["subject"] == "No Subject"


def test_mark_sent_clears_retry_schedule_and_stale_errors():
    service, outbox_collection, orders_collection, processing_collection = _build_service()
    outbox_doc = MagicMock()
    order_doc = MagicMock()
    processing_doc = MagicMock()
    outbox_collection.document.return_value = outbox_doc
    orders_collection.document.return_value = order_doc
    processing_collection.document.return_value = processing_doc
    service.get_email = MagicMock(
        return_value={
            "outbox_id": "outbox-1",
            "event_id": "evt-1",
            "failed_order_id": "order-1",
            "attempt_count": 1,
        }
    )

    assert service.mark_sent("outbox-1", attempts=2) is True

    outbox_payload = outbox_doc.set.call_args_list[0].args[0]
    assert outbox_payload["status"] == EMAIL_STATUS_SENT
    assert outbox_payload["attempt_count"] == 2
    assert outbox_payload["next_attempt_at"] is None
    assert outbox_payload["last_error"] is None

    processing_payload = processing_doc.set.call_args.args[0]
    assert processing_payload["details"]["response_email_status"] == EMAIL_STATUS_SENT
    assert processing_payload["details"]["response_email_last_error"] is None
    assert processing_payload["details"]["feedback_email_status"] == EMAIL_STATUS_SENT
    assert processing_payload["details"]["feedback_email_last_error"] is None

    order_payload = order_doc.set.call_args.args[0]
    assert order_payload["response_email_status"] == EMAIL_STATUS_SENT
    assert order_payload["response_email_last_error"] is None
    assert order_payload["feedback_email_status"] == EMAIL_STATUS_SENT
    assert order_payload["ui_metadata"]["feedback_email_status"] == EMAIL_STATUS_SENT
    assert order_payload["ui_metadata"]["feedback_email_attempts"] == 2
    assert order_payload["ui_metadata"]["feedback_email_last_error"] is None


def test_mark_retry_clears_next_attempt_when_attempts_reach_permanent_failure():
    service, outbox_collection, _orders_collection, _processing_collection = _build_service()
    outbox_doc = MagicMock()
    outbox_collection.document.return_value = outbox_doc
    service.get_email = MagicMock(
        return_value={
            "outbox_id": "outbox-1",
            "event_id": "evt-1",
            "attempt_count": 1,
            "max_attempts": 2,
        }
    )

    status = service.mark_retry("outbox-1", attempts=2, last_error="boom")

    assert status == EMAIL_STATUS_FAILED_PERMANENT
    payload = outbox_doc.set.call_args.args[0]
    assert payload["status"] == EMAIL_STATUS_FAILED_PERMANENT
    assert payload["next_attempt_at"] is None
    assert payload["last_error"] == "boom"
