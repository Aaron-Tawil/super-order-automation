import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.cloud_functions.processor_fn import _queue_and_attempt_response_email, process_order_event
from src.core.events import EmailMetadata, OrderIngestedEvent
from src.core.pipeline import PipelineResult
from src.data.email_outbox_service import EMAIL_STATUS_FAILED_PERMANENT, EMAIL_STATUS_SENT
from src.ingestion.email_outbox_sender import OUTBOX_SEND_SENT
from src.shared.config import settings
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
def mock_save_failed_order_firestore():
    with patch("src.cloud_functions.processor_fn.save_failed_order_to_firestore") as mock:
        yield mock


@pytest.fixture
def mock_init_client():
    with patch("src.cloud_functions.processor_fn.init_client") as mock:
        yield mock


@pytest.fixture
def mock_processing_status():
    with patch("src.cloud_functions.processor_fn.upsert_processing_event") as mock:
        yield mock


@pytest.fixture
def mock_idempotency_service():
    with patch("src.cloud_functions.processor_fn.IdempotencyService") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_email_outbox():
    with (
        patch("src.cloud_functions.processor_fn.EmailOutboxService") as mock_service_cls,
        patch(
            "src.cloud_functions.processor_fn.send_outbox_email",
            return_value=(OUTBOX_SEND_SENT, None),
        ) as mock_send,
    ):
        service = mock_service_cls.return_value
        service.enqueue_email.return_value = "outbox-1"
        service.get_email.return_value = {
            "outbox_id": "outbox-1",
            "attempt_count": 0,
            "thread_id": "thread1",
            "message_id": "msg1",
            "to": "sender@example.com",
            "subject": "Invoice",
            "body": "body",
        }
        yield {"service": service, "send": mock_send}


def create_cloud_event(data: dict):
    """Helper to create a mock CloudEvent."""
    json_data = json.dumps(data)
    data_b64 = base64.b64encode(json_data.encode("utf-8")).decode("utf-8")

    mock_event = MagicMock()
    mock_event.data = {"message": {"data": data_b64}}
    mock_event.id = "evt_123"
    return mock_event


def create_ingested_event(event_id: str = "evt-queued") -> OrderIngestedEvent:
    return OrderIngestedEvent(
        event_id=event_id,
        gcs_uri="gs://bucket/invoice.pdf",
        bucket_name="bucket",
        blob_name="invoice.pdf",
        filename="invoice.pdf",
        mime_type="application/pdf",
        email_metadata=EmailMetadata(
            message_id="msg1",
            thread_id="thread1",
            sender="sender@example.com",
            subject="Invoice",
        ),
    )


def test_queue_and_attempt_response_email_skips_existing_sent_outbox(mock_email_outbox):
    mock_email_outbox["service"].get_email.return_value = {
        "outbox_id": "outbox-1",
        "status": EMAIL_STATUS_SENT,
        "attempt_count": 2,
    }

    status, attempts, outbox_id = _queue_and_attempt_response_email(
        event_id="evt-queued",
        email_type="SUCCESS",
        event=create_ingested_event(),
        body="hello",
        is_html=False,
        gmail_service=MagicMock(),
    )

    assert (status, attempts, outbox_id) == (EMAIL_STATUS_SENT, 2, "outbox-1")
    mock_email_outbox["send"].assert_not_called()
    mock_email_outbox["service"].mark_sent.assert_not_called()
    mock_email_outbox["service"].mark_retry.assert_not_called()


def test_queue_and_attempt_response_email_skips_existing_permanent_failure(mock_email_outbox):
    mock_email_outbox["service"].get_email.return_value = {
        "outbox_id": "outbox-1",
        "status": EMAIL_STATUS_FAILED_PERMANENT,
        "attempt_count": 3,
    }

    status, attempts, outbox_id = _queue_and_attempt_response_email(
        event_id="evt-queued",
        email_type="FAILURE",
        event=create_ingested_event(),
        body="hello",
        is_html=False,
        gmail_service=MagicMock(),
    )

    assert (status, attempts, outbox_id) == (EMAIL_STATUS_FAILED_PERMANENT, 3, "outbox-1")
    mock_email_outbox["send"].assert_not_called()
    mock_email_outbox["service"].mark_failed_permanent.assert_not_called()
    mock_email_outbox["service"].mark_retry.assert_not_called()


def test_process_order_event_success(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
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

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail,
    ):
        mock_gmail.return_value = MagicMock()

        pipeline_instance = mock_pipeline.return_value

        # Use real object instead of mock to avoid Firestore serialization issues in tests
        mock_order = ExtractedOrder(
            invoice_number="INV-123",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)],
        )

        mock_result = PipelineResult(
            orders=[mock_order], supplier_code="S123", supplier_name="Test Supplier", total_cost_usd=0.1
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
    assert save_args.kwargs["metadata"]["sender"] == "sender@example.com"
    assert save_args.kwargs["metadata"]["subject"] == "Invoice 123"
    assert save_args.kwargs["metadata"]["filename"] == "invoice.pdf"
    assert mock_order.is_test is False
    mock_email_outbox["service"].enqueue_email.assert_called()
    mock_email_outbox["send"].assert_called()
    mock_idempotency_service.return_value.mark_message_completed.assert_called()
    assert mock_processing_status.call_count >= 2


def test_process_order_event_success_xlsx(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
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

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail,
    ):
        mock_gmail.return_value = MagicMock()

        pipeline_instance = mock_pipeline.return_value

        mock_order = ExtractedOrder(
            invoice_number="INV-123",
            supplier_global_id=None,
            supplier_email=None,
            supplier_phone=None,
            warnings=[],
            line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)],
        )

        mock_result = PipelineResult(
            orders=[mock_order], supplier_code="S123", supplier_name="Test Supplier", total_cost_usd=0.1
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
    assert save_args.kwargs["metadata"]["sender"] == "sender@example.com"
    assert save_args.kwargs["metadata"]["subject"] == "Invoice 123"
    assert save_args.kwargs["metadata"]["filename"] == "invoice.xlsx"
    assert mock_order.is_test is False
    mock_email_outbox["service"].enqueue_email.assert_called()
    mock_email_outbox["send"].assert_called()
    mock_idempotency_service.return_value.mark_message_completed.assert_called()
    assert mock_processing_status.call_count >= 2


def test_process_order_event_marks_test_sender_orders(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_init_client,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
    monkeypatch,
):
    monkeypatch.setattr(settings, "TEST_ORDER_EMAILS_STR", "test@example.com")
    event_payload = {
        "gcs_uri": "gs://bucket/invoice.pdf",
        "bucket_name": "bucket",
        "blob_name": "invoice.pdf",
        "filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "email_metadata": {
            "message_id": "msg1",
            "thread_id": "thread1",
            "sender": "Test User <test@example.com>",
            "subject": "Invoice Test",
            "received_at": "2023-01-01T12:00:00",
        },
    }
    cloud_event = create_cloud_event(event_payload)

    mock_download.return_value = True
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail,
    ):
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
    assert save_args.kwargs["metadata"]["sender"] == "Test User <test@example.com>"
    assert mock_order.is_test is True
    mock_email_outbox["service"].enqueue_email.assert_called()


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

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service") as _mock_gmail,
    ):
        process_order_event(cloud_event)

    mock_pipeline.return_value.run_pipeline.assert_not_called()
    kwargs = mock_idempotency_service.return_value.mark_message_completed.call_args.kwargs
    assert kwargs["success"] is False
    assert mock_processing_status.call_count >= 2


def test_process_order_event_no_orders(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_save_failed_order_firestore,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
):
    event_payload = {
        "gcs_uri": "gs://bucket/empty.pdf",
        "bucket_name": "bucket",
        "blob_name": "empty.pdf",
        "filename": "empty.pdf",
        "mime_type": "application/pdf",
        "event_id": "event-no-orders",
        "email_metadata": {"message_id": "msg1", "thread_id": "t1", "sender": "s", "subject": "sub"},
    }
    cloud_event = create_cloud_event(event_payload)
    mock_download.return_value = True
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True

    mock_result = PipelineResult(orders=[], total_cost_usd=0.0)
    mock_pipeline.return_value.run_pipeline.return_value = mock_result

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service") as mock_gmail,
    ):
        mock_gmail.return_value = MagicMock()

        process_order_event(cloud_event)

        # "נכשל" is in "נכשל בחילוץ נתוני ההזמנה."
        assert "נכשל" in mock_email_outbox["service"].enqueue_email.call_args.kwargs["body"]

    mock_save_firestore.assert_not_called()
    mock_save_failed_order_firestore.assert_called_once()
    failed_kwargs = mock_save_failed_order_firestore.call_args.kwargs
    assert failed_kwargs["event_id"] == "event-no-orders"
    assert failed_kwargs["source_file_uri"] == "gs://bucket/empty.pdf"
    assert failed_kwargs["filename"] == "empty.pdf"
    assert failed_kwargs["message_id"] == "msg1"
    assert failed_kwargs["thread_id"] == "t1"
    assert failed_kwargs["error"] == "No orders extracted"
    assert failed_kwargs["feedback_email_status"] == "PENDING_RETRY"
    mock_email_outbox["service"].mark_sent.assert_called_once_with("outbox-1", attempts=1)
    final_status_call = mock_processing_status.call_args
    assert final_status_call.kwargs["status"] == "FAILED"
    assert final_status_call.kwargs["stage"] == "EXTRACTION"
    details = final_status_call.kwargs["details"]
    assert details["feedback_email_status"] == "SENT"
    assert details["feedback_email_attempts"] == 1
    assert details["filename"] == "empty.pdf"
    assert details["gcs_uri"] == "gs://bucket/empty.pdf"
    assert details["message_id"] == "msg1"
    assert details["thread_id"] == "t1"
    kwargs = mock_idempotency_service.return_value.mark_message_completed.call_args.kwargs
    assert kwargs["success"] is False
    assert mock_processing_status.call_count >= 2


def test_process_order_event_no_orders_queues_feedback_retry_when_gmail_unavailable(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_save_failed_order_firestore,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
):
    event_payload = {
        "gcs_uri": "gs://bucket/empty.pdf",
        "bucket_name": "bucket",
        "blob_name": "empty.pdf",
        "filename": "empty.pdf",
        "mime_type": "application/pdf",
        "event_id": "event-no-orders-retry",
        "email_metadata": {
            "message_id": "msg1",
            "thread_id": "t1",
            "sender": "sender@example.com",
            "subject": "sub",
        },
    }
    cloud_event = create_cloud_event(event_payload)
    mock_download.return_value = True
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True
    mock_pipeline.return_value.run_pipeline.return_value = PipelineResult(
        orders=[],
        supplier_code="S123",
        supplier_name="Supplier 123",
        total_cost_usd=0.0,
    )

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service", return_value=None),
    ):
        process_order_event(cloud_event)

    mock_email_outbox["send"].assert_not_called()
    mock_email_outbox["service"].mark_waiting.assert_called_once()
    mock_save_firestore.assert_not_called()
    mock_save_failed_order_firestore.assert_called_once()
    failed_kwargs = mock_save_failed_order_firestore.call_args.kwargs
    assert failed_kwargs["feedback_email_status"] == "PENDING_RETRY"
    assert failed_kwargs["feedback_email_attempts"] == 0
    assert failed_kwargs["supplier_code"] == "S123"
    final_status_call = mock_processing_status.call_args
    details = final_status_call.kwargs["details"]
    assert final_status_call.kwargs["status"] == "FAILED"
    assert final_status_call.kwargs["stage"] == "EXTRACTION"
    assert details["feedback_email_status"] == "PENDING_RETRY"
    assert details["feedback_email_attempts"] == 0
    assert details["sender"] == "sender@example.com"
    assert details["subject"] == "sub"
    assert details["supplier_code"] == "S123"


def test_process_order_event_gmail_init_failure_does_not_abort_success(
    mock_pipeline,
    mock_download,
    mock_save_firestore,
    mock_processing_status,
    mock_idempotency_service,
    mock_email_outbox,
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
            "sender": "sender@example.com",
            "subject": "Invoice 123",
            "received_at": "2023-01-01T12:00:00",
        },
    }
    cloud_event = create_cloud_event(event_payload)
    mock_download.return_value = True
    mock_idempotency_service.return_value.check_and_lock_message.return_value = True
    mock_save_firestore.return_value = "order-123"

    mock_order = ExtractedOrder(
        invoice_number="INV-123",
        supplier_global_id=None,
        supplier_email=None,
        supplier_phone=None,
        warnings=[],
        line_items=[LineItem(barcode="7290000000001", description="Test Item", quantity=1.0)],
    )
    mock_pipeline.return_value.run_pipeline.return_value = PipelineResult(
        orders=[mock_order],
        supplier_code="S123",
        supplier_name="Test Supplier",
        total_cost_usd=0.1,
        pending_new_items=[{"barcode": "7290000000001", "name": "Test Item", "item_code": "7290000000001"}],
        new_items_data=[{"barcode": "7290000000001", "description": "Test Item", "final_net_price": 12.3}],
        added_barcodes=["7290000000001"],
    )

    with (
        patch("src.cloud_functions.processor_fn.get_gmail_service", side_effect=RuntimeError("ssl boom")),
        patch("src.cloud_functions.processor_fn.ItemsService") as mock_items_service,
    ):
        process_order_event(cloud_event)

    mock_email_outbox["service"].enqueue_email.assert_called()
    mock_email_outbox["send"].assert_not_called()
    mock_email_outbox["service"].mark_waiting.assert_called_once()
    mock_items_service.return_value.add_new_items_batch.assert_called_once_with(
        [{"barcode": "7290000000001", "name": "Test Item", "item_code": "7290000000001"}]
    )
    assert mock_save_firestore.call_args.kwargs["added_items_barcodes"] is None
    kwargs = mock_idempotency_service.return_value.mark_message_completed.call_args.kwargs
    assert kwargs["success"] is True
    assert mock_processing_status.call_count >= 2
