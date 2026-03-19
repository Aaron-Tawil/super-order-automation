from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.web_api.app import app
from src.web_api.auth import encode_session_cookie


def _auth_cookie() -> tuple[str, str]:
    return ("soa_web_api_session", encode_session_cookie("user@example.com", "Example User", "google"))


def test_auth_session_returns_authenticated_user():
    client = TestClient(app)
    name, value = _auth_cookie()
    client.cookies.set(name, value)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["email"] == "user@example.com"


def test_auth_providers_lists_enabled_entries(monkeypatch):
    monkeypatch.setattr("src.web_api.auth.settings.GOOGLE_CLIENT_ID", "google-id", raising=False)
    monkeypatch.setattr("src.web_api.auth.settings.GOOGLE_CLIENT_SECRET", "google-secret", raising=False)
    monkeypatch.setattr("src.web_api.auth.settings.MICROSOFT_CLIENT_ID", "", raising=False)
    monkeypatch.setattr("src.web_api.auth.settings.MICROSOFT_CLIENT_SECRET", "", raising=False)
    client = TestClient(app)

    response = client.get("/api/v1/auth/providers")

    assert response.status_code == 200
    assert response.json() == [{"provider": "google", "label": "Google"}]


def test_orders_endpoint_serializes_metrics(monkeypatch):
    class FakeOrdersService:
        def list_orders(self, limit=500):
            return [
                {
                    "order_id": "ord-1",
                    "status": "EXTRACTED",
                    "supplier_code": "SUP1",
                    "supplier_name": "Supplier One",
                    "invoice_number": "INV-1",
                    "sender": "ops@example.com",
                    "subject": "Invoice 1",
                    "filename": "inv-1.pdf",
                    "created_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
                    "line_items_count": 3,
                    "warnings_count": 1,
                    "is_test": False,
                    "line_items": [],
                },
                {
                    "order_id": "ord-2",
                    "status": "FAILED",
                    "supplier_code": "UNKNOWN",
                    "supplier_name": "Unknown",
                    "invoice_number": "INV-2",
                    "sender": "ops@example.com",
                    "subject": "Invoice 2",
                    "filename": "inv-2.pdf",
                    "created_at": datetime(2026, 3, 16, 10, 0, tzinfo=UTC),
                    "line_items_count": 0,
                    "warnings_count": 0,
                    "is_test": False,
                    "line_items": [],
                },
            ]

    class FakeSupplierService:
        def get_supplier(self, supplier_code):
            return {"name": supplier_code}

    monkeypatch.setattr("src.web_api.app.OrdersService", FakeOrdersService)
    monkeypatch.setattr("src.web_api.app.SupplierService", FakeSupplierService)

    client = TestClient(app)
    name, value = _auth_cookie()
    client.cookies.set(name, value)

    response = client.get("/api/v1/orders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total"] == 2
    assert payload["metrics"]["completed"] == 1
    assert payload["metrics"]["failed"] == 1
    assert payload["metrics"]["unknown_supplier"] == 1
    assert payload["page_size"] == 10
    assert payload["total_items"] == 2
    assert payload["items"][0]["order_id"] == "ord-1"


def test_order_detail_includes_download_urls(monkeypatch):
    class FakeOrdersService:
        def get_order(self, order_id):
            return {
                "order_id": order_id,
                "status": "EXTRACTED",
                "supplier_code": "SUP1",
                "supplier_name": "Supplier One",
                "invoice_number": "INV-1",
                "sender": "ops@example.com",
                "subject": "Invoice 1",
                "filename": "inv-1.pdf",
                "created_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
                "processing_cost_ils": 1.25,
                "warnings": ["missing vat"],
                "line_items": [
                    {"barcode": "123", "description": "Milk", "quantity": 2, "final_net_price": 18.5}
                ],
            }

    class FakeItemsService:
        def get_items_batch(self, barcodes):
            return [{"barcode": "123", "item_code": "ITEM-123"}]

    monkeypatch.setattr("src.web_api.app.OrdersService", FakeOrdersService)
    monkeypatch.setattr("src.web_api.app.ItemsService", FakeItemsService)

    client = TestClient(app)
    name, value = _auth_cookie()
    client.cookies.set(name, value)

    response = client.get("/api/v1/orders/ord-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["line_items"][0]["item_code"] == "ITEM-123"
    assert payload["source_file_url"].endswith("/api/v1/orders/ord-1/source-file")
    assert payload["export_url"].endswith("/api/v1/orders/ord-1/export.xlsx")
