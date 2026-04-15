from unittest.mock import MagicMock, patch

from src.ingestion.email_outbox_sender import (
    OUTBOX_SEND_PERMANENT_FAILED,
    OUTBOX_SEND_RETRYABLE_FAILED,
    OUTBOX_SEND_SENT,
    send_outbox_email,
)


def test_send_outbox_email_rebuilds_attachments(tmp_path):
    email = {
        "outbox_id": "outbox-1",
        "thread_id": "thread-1",
        "message_id": "msg-1",
        "to": "sender@example.com",
        "subject": "Invoice",
        "body": "<p>hello</p>",
        "is_html": True,
        "attachment_refs": [
            {"type": "gcs_source", "gcs_uri": "gs://bucket/source.pdf", "filename": "source.pdf"},
            {"type": "order_excel", "order_id": "order-1", "filename": "order_INV.xlsx"},
        ],
    }
    order_doc = {
        "invoice_number": "INV",
        "currency": "ILS",
        "vat_status": "EXCLUDED",
        "warnings": [],
        "line_items": [{"barcode": "7290000000001", "description": "Item", "quantity": 1}],
    }

    def fake_download(_gcs_uri, path):
        with open(path, "wb") as fh:
            fh.write(b"pdf")
        return True

    def fake_excel(_order, path):
        with open(path, "wb") as fh:
            fh.write(b"xlsx")

    with (
        patch("src.ingestion.email_outbox_sender.download_file_from_gcs", side_effect=fake_download),
        patch("src.ingestion.email_outbox_sender.OrdersService") as mock_orders_service,
        patch("src.ingestion.email_outbox_sender.generate_excel_from_order", side_effect=fake_excel),
        patch(
            "src.ingestion.email_outbox_sender.send_reply_with_status",
            return_value=(OUTBOX_SEND_SENT, None),
        ) as mock_send_reply,
    ):
        mock_orders_service.return_value.get_order.return_value = order_doc
        status, error = send_outbox_email(email, MagicMock())

    assert status == OUTBOX_SEND_SENT
    assert error is None
    kwargs = mock_send_reply.call_args.kwargs
    assert kwargs["is_html"] is True
    assert sorted(kwargs["attachment_names"].values()) == ["order_INV.xlsx", "source.pdf"]


def test_send_outbox_email_returns_error_when_required_fields_missing():
    status, error = send_outbox_email({"outbox_id": "outbox-1"}, MagicMock())

    assert status == OUTBOX_SEND_PERMANENT_FAILED
    assert "Missing email fields" in error


def test_send_outbox_email_treats_missing_gmail_as_retryable():
    email = {
        "outbox_id": "outbox-1",
        "thread_id": "thread-1",
        "message_id": "msg-1",
        "to": "sender@example.com",
        "subject": "Invoice",
        "body": "hello",
    }

    status, error = send_outbox_email(email, None)

    assert status == OUTBOX_SEND_RETRYABLE_FAILED
    assert error == "Gmail service unavailable"
