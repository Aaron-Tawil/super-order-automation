from unittest.mock import MagicMock, patch

from src.dashboard.order_session import _collect_revertable_barcodes, _get_order_origin_details
from src.ingestion.firestore_writer import save_order_to_firestore


def test_collect_revertable_barcodes_falls_back_to_new_items():
    result = _collect_revertable_barcodes(
        metadata={},
        new_items_data=[
            {"barcode": "123"},
            {"barcode": " 123 "},
            {"barcode": "456"},
            {"barcode": ""},
        ],
    )

    assert result == ["123", "456"]


def test_save_order_to_firestore_persists_added_item_barcodes():
    mock_order = MagicMock()
    mock_order.invoice_number = "INV-1"
    mock_order.model_dump.return_value = {"ui_metadata": {}}

    mock_doc_ref = MagicMock()
    mock_doc_ref.id = "order-123"
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection

    with patch("src.ingestion.firestore_writer.firestore.Client", return_value=mock_db):
        doc_id = save_order_to_firestore(
            mock_order,
            source_file_uri="gs://bucket/order.pdf",
            metadata={"filename": "order.pdf"},
            new_items_data=[{"barcode": "123", "description": "Milk"}],
            added_items_barcodes=["123", " 456 ", ""],
        )

    payload = mock_doc_ref.set.call_args.args[0]
    assert doc_id == "order-123"
    assert payload["new_items"] == [{"barcode": "123", "description": "Milk"}]
    assert payload["ui_metadata"]["added_items_barcodes"] == ["123", "456"]


def test_save_order_to_firestore_persists_ingestion_source_and_sender_email():
    mock_order = MagicMock()
    mock_order.invoice_number = "INV-1"
    mock_order.model_dump.return_value = {"ui_metadata": {}}

    mock_doc_ref = MagicMock()
    mock_doc_ref.id = "order-123"
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection

    with patch("src.ingestion.firestore_writer.firestore.Client", return_value=mock_db):
        save_order_to_firestore(
            mock_order,
            source_file_uri="gs://bucket/order.pdf",
            metadata={
                "ingestion_source": "email",
                "sender": "Test User <test@example.com>",
                "subject": "Invoice",
                "filename": "order.pdf",
            },
        )

    payload = mock_doc_ref.set.call_args.args[0]
    assert payload["ingestion_source"] == "email"
    assert payload["sender_email"] == "test@example.com"
    assert payload["ui_metadata"]["ingestion_source"] == "email"
    assert payload["ui_metadata"]["sender_email"] == "test@example.com"


def test_get_order_origin_details_prefers_persisted_sender_email_for_email_orders():
    details = _get_order_origin_details(
        data={"ingestion_source": "email", "sender_email": "sender@example.com"},
        metadata={},
    )

    assert details["ingestion_source"] == "email"
    assert details["sender_email"] == "sender@example.com"
    assert details["source_label"] == "אימייל"
