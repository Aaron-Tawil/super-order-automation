import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.core.events import EmailMetadata, OrderIngestedEvent
from src.functions.processor_fn import process_order_event
from src.shared.models import ExtractedOrder, LineItem


@pytest.fixture
def mock_processor():
    with patch("src.functions.processor_fn.OrderProcessor") as mock:
        yield mock


@pytest.fixture
def mock_download():
    with patch("src.functions.processor_fn.download_file_from_gcs") as mock:
        yield mock


@pytest.fixture
def mock_save_firestore():
    with patch("src.functions.processor_fn.save_order_to_firestore") as mock:
        yield mock


@pytest.fixture
def mock_init_client():
    with patch("src.functions.processor_fn.init_client") as mock:
        yield mock


def create_cloud_event(data: dict):
    """Helper to create a mock CloudEvent."""
    json_data = json.dumps(data)
    data_b64 = base64.b64encode(json_data.encode("utf-8")).decode("utf-8")

    mock_event = MagicMock()
    mock_event.data = {"message": {"data": data_b64}}
    mock_event.id = "evt_123"
    return mock_event


def test_process_order_event_success(mock_processor, mock_download, mock_save_firestore, mock_init_client):
    # Setup Data
    event_payload = {
        "gcs_uri": "gs://bucket/invoice.pdf",
        "bucket_name": "bucket",
        "blob_name": "invoice.pdf",
        "filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "email_metadata": {
            "message_id": "msg1",
            "thread_id": "thread1",
            "sender": "sender@example.com",
            "subject": "Invoice 123",
            "received_at": "2023-01-01T12:00:00",
        },
    }
    cloud_event = create_cloud_event(event_payload)

    # Mock behaviors
    mock_download.return_value = True

    with patch("src.functions.processor_fn.detect_supplier") as mock_detect, \
         patch("src.functions.processor_fn.SupplierService") as mock_supplier_svc, \
         patch("src.functions.processor_fn.ItemsService") as mock_items_svc, \
         patch("src.functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.functions.processor_fn.send_reply") as mock_reply, \
         patch("src.functions.processor_fn.generate_excel_from_order") as _mock_gen_excel:
        
        mock_detect.return_value = ("S123", 0.95, 0.05, {}, {}, "test@example.com", "123456")
        mock_supplier_svc.return_value.get_supplier.return_value = {"name": "Test Supplier"}
        mock_items_svc.return_value.get_new_barcodes.return_value = []
        mock_gmail.return_value = MagicMock()

        processor_instance = mock_processor.return_value
        
        # Use real object instead of mock to avoid Firestore serialization issues in tests
        mock_order = ExtractedOrder(
            invoice_number="INV-123",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)]
        )
        processor_instance.process_file.return_value = ([mock_order], 0.1, 0, 0)

        # Run
        process_order_event(cloud_event)

    # Verify
    mock_download.assert_called_with("gs://bucket/invoice.pdf", "/tmp/invoice.pdf")
    processor_instance.process_file.assert_called_once()
    mock_save_firestore.assert_called_with(mock_order, "gs://bucket/invoice.pdf")
    mock_reply.assert_called()


def test_process_order_event_download_fail(mock_processor, mock_download):
    event_payload = {
        "gcs_uri": "gs://bucket/fail.pdf",
        "bucket_name": "bucket",
        "blob_name": "fail.pdf",
        "filename": "fail.pdf",
        "mime_type": "application/pdf",
        "email_metadata": {"message_id": "msg1", "thread_id": "t1", "sender": "s", "subject": "sub"},
    }
    cloud_event = create_cloud_event(event_payload)
    mock_download.return_value = False  # Fail download

    with patch("src.functions.processor_fn.get_gmail_service") as _mock_gmail, \
         patch("src.functions.processor_fn.send_reply") as _mock_reply:
        process_order_event(cloud_event)

    mock_processor.return_value.process_file.assert_not_called()


def test_process_order_event_no_orders(mock_processor, mock_download, mock_save_firestore):
    event_payload = {
        "gcs_uri": "gs://bucket/empty.pdf",
        "bucket_name": "bucket",
        "blob_name": "empty.pdf",
        "filename": "empty.pdf",
        "mime_type": "application/pdf",
        "email_metadata": {"message_id": "msg1", "thread_id": "t1", "sender": "s", "subject": "sub"},
    }
    cloud_event = create_cloud_event(event_payload)
    mock_download.return_value = True
    mock_processor.return_value.process_file.return_value = ([], 0.0, 0, 0)  # No orders

    with patch("src.functions.processor_fn.detect_supplier") as mock_detect, \
         patch("src.functions.processor_fn.SupplierService") as _mock_supplier_svc, \
         patch("src.functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.functions.processor_fn.send_reply") as mock_reply:
        
        mock_detect.return_value = ("UNKNOWN", 0.0, 0.0, {}, {}, None, None)
        mock_gmail.return_value = MagicMock()
        
        process_order_event(cloud_event)
        
        mock_reply.assert_called_once()
        # "נכשל" is in "נכשל בחילוץ נתוני ההזמנה."
        assert "נכשל" in mock_reply.call_args[0][5]

    mock_save_firestore.assert_not_called()
