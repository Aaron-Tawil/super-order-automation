from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_dashboard_load():
    """Test that the dashboard loads without error."""
    # Patch dependencies used at module level or early import
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
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
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
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
        patch("src.dashboard.inbox.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        button_labels = [button.label for button in at.button]
        assert any("תיבת הזמנות" in label for label in button_labels)
        assert any("העלאה ידנית" in label for label in button_labels)
        assert any("ניהול ספקים" in label for label in button_labels)
        assert any("ניהול פריטים" in label for label in button_labels)
