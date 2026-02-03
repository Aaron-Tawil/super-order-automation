import sys
import os
import json
from pydantic import ValidationError

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.shared.models import ExtractedOrder, LineItem, VatStatus

def test_validation_fix():
    print("Testing ExtractedOrder validation with NULL values...")

    # JSON with nulls in numeric fields
    raw_json = """
    {
        "supplier_name": "Test Supplier",
        "date": "2023-10-27",
        "invoice_number": "12345",
        "currency": "ILS",
        "line_items": [
            {
                "description": "Valid Item",
                "quantity": 5.0,
                "raw_unit_price": 10.0,
                "final_net_price": 10.0,
                "vat_status": "EXCLUDED"
            },
            {
                "description": "Problematic Item with Nulls",
                "quantity": null,
                "raw_unit_price": null,
                "final_net_price": null,
                "vat_status": "EXCLUDED"
            }
        ]
    }
    """

    try:
        order = ExtractedOrder.model_validate_json(raw_json)
        print("✅ Validation successful!")
        
        # Check defaults
        bad_item = order.line_items[1]
        print(f"Item 2 Quantity: {bad_item.quantity} (Expected 0.0)")
        print(f"Item 2 Price: {bad_item.raw_unit_price} (Expected 0.0)")
        
        assert bad_item.quantity == 0.0
        assert bad_item.raw_unit_price == 0.0
        assert bad_item.final_net_price == 0.0
        print("✅ Defaults valid.")

    except ValidationError as e:
        print("❌ Validation Failed!")
        print(e)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_validation_fix()
