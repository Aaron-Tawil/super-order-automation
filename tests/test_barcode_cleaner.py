import sys
import os
from pydantic import ValidationError

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.shared.models import LineItem, VatStatus

def test_barcode_cleaning():
    print("Testing Barcode Cleaning Logic...")

    test_cases = [
        ("7290017447575", "7290017447575", "Clean barcode should remain unchanged"),
        ("729001 744757 5", "7290017447575", "Spaces should be removed"),
        ("729001-744757-5", "7290017447575", "Hyphens should be removed"),
        ("  729001\n744757\n5  ", "7290017447575", "Newlines and spaces should be removed"),
        ("ABC-123", "123", "Letters should be removed"),
        ("", None, "Empty string should result in None"),
        (None, None, "None should result in None"),
        ("   ", None, "Whitespace string should result in None")
    ]

    for raw_input, expected, description in test_cases:
        print(f"Testing: '{raw_input}' -> Expecting: '{expected}' ({description})")
        try:
            item = LineItem(
                description="Test Item",
                barcode=raw_input,
                vat_status=VatStatus.EXCLUDED
            )
            
            if item.barcode == expected:
                print(f"  ✅ PASS: Got '{item.barcode}'")
            else:
                print(f"  ❌ FAIL: Got '{item.barcode}', Expected '{expected}'")
                sys.exit(1)
                
        except ValidationError as e:
            print(f"  ❌ Validation Error: {e}")
            sys.exit(1)
            
    print("\n✅ All barcode tests passed!")

if __name__ == "__main__":
    test_barcode_cleaning()
