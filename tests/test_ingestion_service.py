from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.core.events import EmailMetadata, OrderIngestedEvent
from src.ingestion.ingestor import IngestionService
from src.shared.config import settings


@pytest.fixture
def mock_publisher():
    with patch("src.ingestion.ingestor.pubsub_v1.PublisherClient") as mock:
        yield mock


@pytest.fixture
def mock_upload():
    with patch("src.ingestion.ingestor.upload_to_gcs") as mock:
        yield mock


@pytest.fixture
def mock_gmail_service():
    with patch("src.ingestion.ingestor.get_gmail_service") as mock:
        yield mock


@pytest.fixture
def mock_idempotency():
    with patch("src.shared.idempotency_service.IdempotencyService") as mock:
        yield mock


def test_ingestion_service_init(mock_publisher):
    # Ensure we use the actual project_id from settings for the assertion
    expected_project_id = settings.PROJECT_ID
    service = IngestionService()
    assert service.project_id == expected_project_id
    assert service.topic_id == "order-ingestion-topic"
    service.publisher.topic_path.assert_called_with(expected_project_id, "order-ingestion-topic")


def test_publish_event(mock_publisher):
    service = IngestionService()
    # Mock future result
    mock_future = MagicMock()
    mock_future.result.return_value = "msg_123"
    service.publisher.publish.return_value = mock_future

    event = OrderIngestedEvent(
        gcs_uri="gs://bucket/file.pdf",
        bucket_name="bucket",
        blob_name="file.pdf",
        filename="file.pdf",
        mime_type="application/pdf",
        email_metadata=EmailMetadata(
            message_id="msg1", thread_id="thread1", sender="sender@example.com", subject="Invoice"
        ),
    )

    msg_id = service.publish_event(event)

    assert msg_id == "msg_123"
    service.publisher.publish.assert_called_once()

    # Check payload
    args, _ = service.publisher.publish.call_args
    pub_data = args[1]
    assert b"gs://bucket/file.pdf" in pub_data


def test_process_unread_emails_async_no_emails(mock_gmail_service, mock_publisher):
    # Setup mock service
    service_mock = MagicMock()
    mock_gmail_service.return_value = service_mock

    # Mock empty list results - handle chained calls with arguments
    service_mock.users.return_value.messages.return_value.list.return_value.execute.return_value = {"messages": []}

    ingestor = IngestionService()
    count = ingestor.process_unread_emails_async()

    assert count == 0
    service_mock.users.return_value.messages.return_value.list.assert_called_once()


@patch("src.ingestion.ingestor.IdempotencyService")
def test_process_unread_emails_async_success(mock_idempotency_cls, mock_gmail_service, mock_publisher, mock_upload):
    # Setup mocks
    service_mock = MagicMock()
    mock_gmail_service.return_value = service_mock

    mock_idempotency = mock_idempotency_cls.return_value
    mock_idempotency.check_and_lock_message.return_value = True

    mock_upload.return_value = "gs://test-bucket/invoice.pdf"

    # Mock list results - use return_value to handle chained calls with arguments
    service_mock.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "msg_123", "threadId": "thread_123"}]
    }

    # Mock get message details
    service_mock.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "msg_123",
        "threadId": "thread_123",
        "labelIds": ["UNREAD"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Invoice #100"},
                {"name": "From", "value": "supplier@example.com"},
            ],
            "parts": [{"filename": "invoice.pdf", "body": {"attachmentId": "att_123"}, "mimeType": "application/pdf"}],
        },
    }

    # Mock get attachment
    service_mock.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
        "data": "bW9jayBkYXRh"  # base64 for "mock data"
    }

    # Mock profile for self-check
    service_mock.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "me@example.com"}

    # Run
    ingestor = IngestionService()
    # Mock publish to succeed
    mock_future = MagicMock()
    mock_future.result.return_value = "pub_msg_1"
    ingestor.publisher.publish.return_value = mock_future

    count = ingestor.process_unread_emails_async()

    assert count == 1

    # Verifications
    mock_idempotency.check_and_lock_message.assert_called_with("msg_123")
    service_mock.users.return_value.messages.return_value.modify.assert_called()
    mock_upload.assert_called()
    ingestor.publisher.publish.assert_called_once()
    mock_idempotency.mark_message_completed.assert_called_with("msg_123", success=True)
