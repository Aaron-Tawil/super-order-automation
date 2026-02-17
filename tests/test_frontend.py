from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest


def test_dashboard_load():
    """Test that the dashboard loads without error."""
    # Patch dependencies used at module level or early import
    with (
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Check basic elements
        assert not at.exception
        # "🧾 מערכת אוטומציה להזמנות" is the Hebrew title
        assert "אוטומציה" in at.title[0].value


def test_dashboard_file_upload_ui():
    """Test that file upload widget is present when not coming from email."""
    # Mock session state empty
    with (
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Should see file uploader
        # Use get() as a fallback or check if it's in the list of widgets
        assert len(at.get("file_uploader")) > 0


def test_dashboard_navigation():
    """Test sidebar navigation."""
    with (
        patch("src.dashboard.app.init_client"),
        patch("src.dashboard.app.get_session"),
        patch("src.data.items_service.ItemsService"),
        patch("src.data.supplier_service.SupplierService"),
    ):
        at = AppTest.from_file("src/dashboard/app.py")
        at.run()

        # Sidebar buttons
        # "🏠 דשבורד", "🏢 ספקים", "📦 פריטים"
        assert len(at.sidebar.button) >= 3
        assert "דשבורד" in at.sidebar.button[0].label
