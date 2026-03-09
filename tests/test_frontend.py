from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest


def test_dashboard_load():
    """Test that the dashboard loads without error."""
    # Patch dependencies used at module level or early import
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.dashboard.app.OrdersService"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Check basic elements
        assert not at.exception
        # Dashboard is the default view and inbox is embedded below it.
        assert any("מערכת אוטומציה להזמנות" in title.value for title in at.title)
        assert any("תיבת הזמנות" in title.value for title in at.title)


def test_dashboard_file_upload_ui():
    """Test that file upload widget is present on order workspace."""
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.dashboard.app.OrdersService"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.session_state["page"] = "dashboard"
        at.run()

        # Should see file uploader
        # Use get() as a fallback or check if it's in the list of widgets
        assert len(at.get("file_uploader")) > 0


def test_dashboard_navigation():
    """Test sidebar navigation."""
    with (
        patch("src.dashboard.auth.require_login"),
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.dashboard.app.OrdersService"),
        patch("src.dashboard.inbox.OrdersService") as mock_orders_service,
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        mock_orders_service.return_value.list_orders.return_value = []
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Sidebar buttons
        # "🏠 דשבורד", "⚙️ ניהול ספקים", "📦 ניהול פריטים"
        assert len(at.sidebar.button) >= 3
        assert "דשבורד" in at.sidebar.button[0].label
