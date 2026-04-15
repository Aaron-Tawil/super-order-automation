from datetime import UTC, datetime
from unittest.mock import patch

from src.dashboard import inbox


def test_load_orders_merges_failed_processing_events():
    inbox._load_orders.clear()
    order = {
        "order_id": "order-1",
        "created_at": datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
        "status": "EXTRACTED",
        "supplier_code": "S1",
        "line_items": [],
    }
    failed_event = {
        "event_id": "event-1",
        "record_type": "processing_event",
        "created_at": datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
        "status": "FAILED",
        "stage": "EXTRACTION",
        "supplier_code": "S2",
        "error": "No orders extracted",
        "line_items": [],
    }

    with (
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_events_service,
    ):
        mock_orders_service.return_value.list_orders.return_value = [order]
        mock_events_service.return_value.list_failed_events.return_value = [failed_event]

        rows = inbox._load_orders()

    assert [row.get("event_id") or row.get("order_id") for row in rows] == ["event-1", "order-1"]
    assert sum(1 for row in rows if inbox._normalize_status(row.get("status")) == "FAILED") == 1


def test_load_orders_dedupes_failed_event_when_failed_order_exists():
    inbox._load_orders.clear()
    failed_order = {
        "order_id": "failed-order-1",
        "event_id": "event-1",
        "record_type": "failed_order",
        "created_at": datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
        "status": "FAILED",
        "supplier_code": "S2",
        "line_items": [],
    }
    failed_event = {
        "event_id": "event-1",
        "record_type": "processing_event",
        "created_at": datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
        "status": "FAILED",
        "supplier_code": "S2",
        "line_items": [],
    }

    with (
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_events_service,
    ):
        mock_orders_service.return_value.list_orders.return_value = [failed_order]
        mock_events_service.return_value.list_failed_events.return_value = [failed_event]

        rows = inbox._load_orders()

    assert rows == [failed_order]


def test_build_order_link_routes_failed_events_to_failed_detail(monkeypatch):
    monkeypatch.setattr(inbox.settings, "WEB_UI_URL", "https://dashboard.example.com", raising=False)
    monkeypatch.setattr(inbox.settings, "ENVIRONMENT", "cloud", raising=False)

    link = inbox._build_order_link({"record_type": "processing_event", "event_id": "event-1"})

    assert link == "https://dashboard.example.com/?failed_event_id=event-1"


def test_build_order_link_routes_failed_orders_to_failed_detail(monkeypatch):
    monkeypatch.setattr(inbox.settings, "WEB_UI_URL", "https://dashboard.example.com", raising=False)
    monkeypatch.setattr(inbox.settings, "ENVIRONMENT", "cloud", raising=False)

    link = inbox._build_order_link({"record_type": "failed_order", "event_id": "event-1"})

    assert link == "https://dashboard.example.com/?failed_event_id=event-1"
