from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from google.cloud import firestore

from src.data.email_outbox_service import EMAIL_STATUS_PENDING, EmailOutboxService


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
