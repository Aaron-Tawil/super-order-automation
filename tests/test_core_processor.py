import unittest
from unittest.mock import MagicMock, patch

from src.core.processor import OrderProcessor

# Using string enum for VatStatus in models.py: VatStatus.EXCLUDED
from src.shared.models import ExtractedOrder, LineItem, VatStatus


class TestOrderProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = OrderProcessor()

    @patch("src.core.processor.vertex_client")
    def test_process_file_basic_flow(self, mock_vertex):
        # Setup mock return
        mock_order = ExtractedOrder(
            invoice_number="INV123",
            line_items=[
                LineItem(description="Item 1", quantity=10, raw_unit_price=10.0, vat_status=VatStatus.EXCLUDED)
            ],
            document_total_with_vat=117.0,  # 10*10 * 1.17 (assuming 17% VAT)
            vat_rate=17.0,
            document_total_quantity=10,
        )
        mock_vertex.extract_invoice_data.return_value = ([mock_order], 0.01, {}, {})

        # Call process
        orders, _, _, _ = self.processor.process_file("dummy.pdf")

        # Verify
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].invoice_number, "INV123")
        self.assertEqual(len(orders[0].warnings), 0)
        mock_vertex.extract_invoice_data.assert_called_once()

    @patch("src.core.processor.vertex_client")
    def test_post_process_promotions(self, mock_vertex):
        # Setup specific case for 11+1
        # Item A, qty=11, price=10
        # Item A, qty=1, price=0
        # Total cost = 110. Total qty = 12. Avg price = 110/12 = 9.1666...

        mock_order = ExtractedOrder(
            line_items=[
                LineItem(
                    barcode="123", description="A", quantity=11, raw_unit_price=10.0, vat_status=VatStatus.EXCLUDED
                ),
                LineItem(
                    barcode="123",
                    description="A (Bonus)",
                    quantity=1,
                    raw_unit_price=0.0,
                    vat_status=VatStatus.EXCLUDED,
                ),
            ],
            document_total_with_vat=128.7,  # 110 * 1.17
            vat_rate=17.0,
        )
        mock_vertex.extract_invoice_data.return_value = ([mock_order], 0.01, {}, {})

        orders, _, _, _ = self.processor.process_file("dummy.pdf")

        items = orders[0].line_items
        self.assertEqual(len(items), 2)
        # Check avg price applied to both
        expected = 110.0 / 12.0
        self.assertAlmostEqual(items[0].final_net_price, expected, places=4)
        self.assertAlmostEqual(items[1].final_net_price, expected, places=4)

    @patch("src.core.processor.vertex_client")
    def test_validation_failure_creates_warning(self, mock_vertex):
        # Setup order with bad total
        mock_order = ExtractedOrder(
            invoice_number="BAD_TOTAL",
            line_items=[LineItem(description="A", quantity=1, final_net_price=100.0, vat_status=VatStatus.EXCLUDED)],
            document_total_with_vat=50.0,  # Should be 117.0
            vat_rate=17.0,
        )
        mock_vertex.extract_invoice_data.return_value = ([mock_order], 0.01, {}, {})

        orders, _, _, _ = self.processor.process_file("dummy.pdf")

        # Should have warnings (and will have retried)
        self.assertEqual(len(orders), 1)
        self.assertGreater(len(orders[0].warnings), 0)
        self.assertTrue(any("total" in w.lower() for w in orders[0].warnings))


if __name__ == "__main__":
    unittest.main()
