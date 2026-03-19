from unittest.mock import MagicMock, patch

from src.core.pipeline import ExtractionPipeline
from src.shared.models import ExtractedOrder, LineItem


@patch("src.core.pipeline.OrderProcessor")
@patch("src.core.pipeline.LocalSupplierDetector")
@patch("src.core.pipeline.ItemsService")
@patch("src.core.pipeline.SupplierService")
def test_pipeline_stages_new_items_without_persisting(
    mock_supplier_service,
    mock_items_service,
    mock_local_detector,
    mock_order_processor,
):
    mock_local_detector.return_value.detect_supplier.return_value = ("SUP1", 0.95, "sender_match")
    mock_supplier_service.return_value.get_supplier.return_value = {
        "name": "Supplier 1",
        "special_instructions": None,
    }
    mock_items_service.return_value.get_new_barcodes.return_value = ["7290000000001"]

    order = ExtractedOrder(
        invoice_number="INV-1",
        supplier_global_id=None,
        supplier_email=None,
        supplier_phone=None,
        warnings=[],
        line_items=[
            LineItem(
                barcode="7290000000001",
                description="Milk",
                quantity=2,
                final_net_price=5.5,
            )
        ],
    )
    mock_order_processor.return_value.process_file.return_value = ([order], 0.25, {"1": {}}, {})

    pipeline = ExtractionPipeline()
    result = pipeline.run_pipeline(
        file_path="invoice.pdf",
        mime_type="application/pdf",
        email_metadata={"body": "body"},
    )

    assert result.new_items_added == 1
    assert result.added_barcodes == ["7290000000001"]
    assert result.pending_new_items == [
        {"barcode": "7290000000001", "name": "Milk", "item_code": "7290000000001"}
    ]
    assert result.new_items_data == [
        {"barcode": "7290000000001", "description": "Milk", "final_net_price": 5.5}
    ]
    mock_items_service.return_value.add_new_items_batch.assert_not_called()
