from datetime import UTC, datetime
from unittest.mock import MagicMock

from google.cloud import firestore

from src.data.processing_events_service import ProcessingEventsService


def test_list_failed_events_orders_before_limit():
    db = MagicMock()
    collection = db.collection.return_value
    failed_query = collection.where.return_value
    ordered_query = failed_query.order_by.return_value
    limited_query = ordered_query.limit.return_value

    doc = MagicMock()
    doc.id = "event-1"
    doc.to_dict.return_value = {
        "event_id": "event-1",
        "status": "FAILED",
        "stage": "EXTRACTION",
        "updated_at": datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
        "details": {"error": "No orders extracted"},
    }
    limited_query.stream.return_value = [doc]

    service = ProcessingEventsService(firestore_client=db)
    events = service.list_failed_events(limit=100)

    assert collection.where.call_args.kwargs["filter"] is not None
    failed_query.order_by.assert_called_once_with("updated_at", direction=firestore.Query.DESCENDING)
    ordered_query.limit.assert_called_once_with(100)
    assert events[0]["event_id"] == "event-1"
    assert events[0]["error"] == "No orders extracted"


def test_list_failed_events_falls_back_when_index_missing():
    db = MagicMock()
    collection = db.collection.return_value
    indexed_failed_query = MagicMock()
    indexed_failed_query.order_by.return_value.limit.return_value.stream.side_effect = Exception(
        "The query requires an index"
    )
    fallback_query = MagicMock()
    collection.where.side_effect = [indexed_failed_query, fallback_query]

    older_doc = MagicMock()
    older_doc.id = "older"
    older_doc.to_dict.return_value = {
        "event_id": "older",
        "status": "FAILED",
        "updated_at": datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
        "details": {"error": "older"},
    }
    newer_doc = MagicMock()
    newer_doc.id = "newer"
    newer_doc.to_dict.return_value = {
        "event_id": "newer",
        "status": "FAILED",
        "updated_at": datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
        "details": {"error": "newer"},
    }
    fallback_query.stream.return_value = [older_doc, newer_doc]

    service = ProcessingEventsService(firestore_client=db)
    events = service.list_failed_events(limit=1)

    assert [event["event_id"] for event in events] == ["newer"]
