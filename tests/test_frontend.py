from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_dashboard_load():
    """Test that the dashboard loads without error."""
    # Patch dependencies used at module level or early import
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_events_service,
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        mock_events_service.return_value.list_failed_events.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Check basic elements
        assert not at.exception
        # The default route is now the inbox page.
        assert any("מערכת אוטומציה להזמנות" in title.value for title in at.title)
        assert any("תיבת הזמנות" in title.value for title in at.title)


def test_dashboard_file_upload_ui():
    """Test that file upload widget is present on order workspace."""
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_events_service,
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        mock_events_service.return_value.list_failed_events.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.session_state["page"] = "upload"
        at.run()

        # Should see file uploader
        assert len(at.get("file_uploader")) > 0


def test_dashboard_navigation():
    """Test primary navigation buttons."""
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_events_service,
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        mock_events_service.return_value.list_failed_events.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        button_labels = [button.label for button in at.button]
        assert any("תיבת הזמנות" in label for label in button_labels)
        assert any("העלאה ידנית" in label for label in button_labels)
        assert any("ניהול ספקים" in label for label in button_labels)
        assert any("ניהול פריטים" in label for label in button_labels)


def test_dashboard_failed_event_route():
    """Failed processing events open a read-only failure page instead of the order editor."""
    failed_event = {
        "event_id": "event-1",
        "status": "FAILED",
        "stage": "EXTRACTION",
        "created_at": None,
        "updated_at": None,
        "supplier_code": "S123",
        "supplier_name": "Supplier 123",
        "filename": "invoice.pdf",
        "gcs_uri": "gs://bucket/invoice.pdf",
        "sender": "sender@example.com",
        "subject": "Invoice",
        "message_id": "msg-1",
        "thread_id": "thread-1",
        "error": "No orders extracted",
        "feedback_email_status": "PENDING_RETRY",
        "feedback_email_attempts": 0,
    }
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_inbox_events_service,
        patch("src.dashboard.inbox.SupplierService"),
        patch("src.dashboard.failed_event.ProcessingEventsService") as mock_failed_events_service,
        patch("src.dashboard.failed_event.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        mock_inbox_events_service.return_value.list_failed_events.return_value = [failed_event]
        mock_failed_events_service.return_value.get_event.return_value = failed_event
        at = AppTest.from_file("src/dashboard/app.py")
        at.query_params["failed_event_id"] = "event-1"
        at.run()

        assert not at.exception
        assert any("פרטי כשל בעיבוד" in subheader.value for subheader in at.subheader)
        assert any("No orders extracted" in error.value for error in at.error)


def test_dashboard_does_not_restore_stale_failed_event_when_on_inbox():
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.ProcessingEventsService") as mock_inbox_events_service,
        patch("src.dashboard.inbox.SupplierService"),
        patch("src.dashboard.failed_event.ProcessingEventsService") as mock_failed_events_service,
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        mock_inbox_events_service.return_value.list_failed_events.return_value = []

        at = AppTest.from_file("src/dashboard/app.py")
        at.session_state["page"] = "inbox"
        at.session_state["active_failed_event_id"] = "stale-event"
        at.run()

        assert not at.exception
        assert any("תיבת הזמנות" in title.value for title in at.title)
        mock_failed_events_service.return_value.get_event.assert_not_called()
