import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.cloud_functions.processor_fn import process_order_event
from src.core.pipeline import PipelineResult
from src.shared.models import ExtractedOrder, LineItem


@pytest.fixture
def mock_pipeline():
    with patch("src.core.pipeline.ExtractionPipeline") as mock:
        yield mock


@pytest.fixture
def mock_download():
    with patch("src.cloud_functions.processor_fn.download_file_from_gcs") as mock:
        yield mock


@pytest.fixture
def mock_save_firestore():
    with patch("src.cloud_functions.processor_fn.save_order_to_firestore") as mock:
        yield mock


@pytest.fixture
def mock_init_client():
    with patch("src.cloud_functions.processor_fn.init_client") as mock:
        yield mock


@pytest.fixture
def mock_create_session():
    with patch("src.cloud_functions.processor_fn.create_session") as mock:
        mock.return_value = "session-test-123"
        yield mock


@pytest.fixture
def mock_processing_status():
    with patch("src.cloud_functions.processor_fn.upsert_processing_event") as mock:
        yield mock


@pytest.fixture
def mock_idempotency_service():
    with patch("src.cloud_functions.processor_fn.IdempotencyService") as mock:
        yield mock


def create_cloud_event(data: dict):
    """Helper to create a mock CloudEvent."""
    json_data = json.dumps(data)
    data_b64 = base64.b64encode(json_data.encode("utf-8")).decode("utf-8")

    mock_event = MagicMock()
    mock_event.data = {"message": {"data": data_b64}}
    mock_event.id = "evt_123"
    return mock_event


def test_process_order_event_success(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_create_session,
    mock_processing_status,
    mock_idempotency_service,
):
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
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    with patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.cloud_functions.processor_fn.send_reply") as mock_reply, \
         patch("src.cloud_functions.processor_fn.generate_new_items_excel") as _mock_gen_excel:
        
        mock_gmail.return_value = MagicMock()

        pipeline_instance = mock_pipeline.return_value
        
        # Use real object instead of mock to avoid Firestore serialization issues in tests
        mock_order = ExtractedOrder(
            invoice_number="INV-123",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)]
        )
        
        mock_result = PipelineResult(
            orders=[mock_order],
            supplier_code="S123",
            supplier_name="Test Supplier",
            total_cost_usd=0.1
        )
        pipeline_instance.run_pipeline.return_value = mock_result

        # Run
        process_order_event(cloud_event)

    # Verify
    download_args = mock_download.call_args[0]
    assert download_args[0] == "gs://bucket/invoice.pdf"
    assert download_args[1].endswith(".pdf")
    pipeline_instance.run_pipeline.assert_called_once()
    save_args = mock_save_firestore.call_args
    assert save_args.args == (mock_order, "gs://bucket/invoice.pdf")
    assert save_args.kwargs["is_test"] is False
    assert save_args.kwargs["session_id"] == "session-test-123"
    assert save_args.kwargs["metadata"]["sender"] == "sender@example.com"
    assert save_args.kwargs["metadata"]["subject"] == "Invoice 123"
    assert save_args.kwargs["metadata"]["filename"] == "invoice.pdf"
    assert mock_order.is_test is False
    mock_reply.assert_called()
    mock_idempotency_service.return_value.mark_message_completed.assert_called()
    assert mock_processing_status.call_count >= 2


def test_process_order_event_success_xlsx(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_create_session,
    mock_processing_status,
    mock_idempotency_service,
):
    # Setup Data
    event_payload = {
        "gcs_uri": "gs://bucket/invoice.xlsx",
        "bucket_name": "bucket",
        "blob_name": "invoice.xlsx",
        "filename": "invoice.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    with patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.cloud_functions.processor_fn.send_reply") as mock_reply, \
         patch("src.cloud_functions.processor_fn.generate_new_items_excel") as _mock_gen_excel:
        
        mock_gmail.return_value = MagicMock()

        pipeline_instance = mock_pipeline.return_value
        
        mock_order = ExtractedOrder(
            invoice_number="INV-123",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)]
        )
        
        mock_result = PipelineResult(
            orders=[mock_order],
            supplier_code="S123",
            supplier_name="Test Supplier",
            total_cost_usd=0.1
        )
        pipeline_instance.run_pipeline.return_value = mock_result

        # Run
        process_order_event(cloud_event)

    # Verify
    download_args = mock_download.call_args[0]
    assert download_args[0] == "gs://bucket/invoice.xlsx"
    assert download_args[1].endswith(".xlsx")
    pipeline_instance.run_pipeline.assert_called_once()
    save_args = mock_save_firestore.call_args
    assert save_args.args == (mock_order, "gs://bucket/invoice.xlsx")
    assert save_args.kwargs["is_test"] is False
    assert save_args.kwargs["session_id"] == "session-test-123"
    assert save_args.kwargs["metadata"]["sender"] == "sender@example.com"
    assert save_args.kwargs["metadata"]["subject"] == "Invoice 123"
    assert save_args.kwargs["metadata"]["filename"] == "invoice.xlsx"
    assert mock_order.is_test is False
    mock_reply.assert_called()
    mock_idempotency_service.return_value.mark_message_completed.assert_called()
    assert mock_processing_status.call_count >= 2


def test_process_order_event_marks_test_sender_orders(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_create_session,
    mock_processing_status,
    mock_idempotency_service,
):
    event_payload = {
        "gcs_uri": "gs://bucket/invoice.pdf",
        "bucket_name": "bucket",
        "blob_name": "invoice.pdf",
        "filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "email_metadata": {
            "message_id": "msg1",
            "thread_id": "thread1",
            "sender": "Aaron Test <aarondavidtawil@gmail.com>",
            "subject": "Invoice Test",
            "received_at": "2023-01-01T12:00:00",
        },
    }
    cloud_event = create_cloud_event(event_payload)

    mock_download.return_value = True
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    with patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.cloud_functions.processor_fn.send_reply") as mock_reply, \
         patch("src.cloud_functions.processor_fn.generate_new_items_excel") as _mock_gen_excel:
        mock_gmail.return_value = MagicMock()

        pipeline_instance = mock_pipeline.return_value
        mock_order = ExtractedOrder(
            invoice_number="INV-TEST",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)],
        )
        pipeline_instance.run_pipeline.return_value = PipelineResult(
            orders=[mock_order],
            supplier_code="S123",
            supplier_name="Test Supplier",
            total_cost_usd=0.1,
        )

        process_order_event(cloud_event)

    save_args = mock_save_firestore.call_args
    assert save_args.args == (mock_order, "gs://bucket/invoice.pdf")
    assert save_args.kwargs["is_test"] is True
    assert save_args.kwargs["session_id"] == "session-test-123"
    assert save_args.kwargs["metadata"]["sender"] == "Aaron Test <aarondavidtawil@gmail.com>"
    assert mock_order.is_test is True
    mock_reply.assert_called()


def test_process_order_event_download_fail(
    mock_pipeline,
    mock_download,
    mock_processing_status,
    mock_idempotency_service,
):
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
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    with patch("src.cloud_functions.processor_fn.get_gmail_service") as _mock_gmail, \
         patch("src.cloud_functions.processor_fn.send_reply") as _mock_reply:
        process_order_event(cloud_event)

    mock_pipeline.return_value.run_pipeline.assert_not_called()
    kwargs = mock_idempotency_service.return_value.mark_message_completed.call_args.kwargs
    assert kwargs["success"] is False
    assert mock_processing_status.call_count >= 2


def test_process_order_event_no_orders(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_processing_status,
    mock_idempotency_service,
):
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
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True
    
    mock_result = PipelineResult(orders=[], total_cost_usd=0.0)
    mock_pipeline.return_value.run_pipeline.return_value = mock_result

    with patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail, \
         patch("src.cloud_functions.processor_fn.send_reply") as mock_reply:
        
        mock_gmail.return_value = MagicMock()
        
        process_order_event(cloud_event)
        
        mock_reply.assert_called_once()
        # "נכשל" is in "נכשל בחילוץ נתוני ההזמנה."
        assert "נכשל" in mock_reply.call_args[0][5]

    mock_save_firestore.assert_not_called()
    kwargs = mock_idempotency_service.return_value.mark_message_completed.call_args.kwargs
    assert kwargs["success"] is False
    assert mock_processing_status.call_count >= 2
