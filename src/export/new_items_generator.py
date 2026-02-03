"""
New Items Excel Generator.

Generates an Excel file for new items (items with barcodes not in our database)
in the format matching new-items-format.xlsx.

Output columns:
- ברקוד: Barcode
- שם פריט: Item name
- ברקוד 2: Secondary barcode (copy of primary)
- מכירה: Selling price
- עלות נטו: Net cost
- מספר ספק: Supplier code
"""

import pandas as pd
from typing import List
import os
import sys

# Add project root to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.models import ExtractedOrder, LineItem
from src.shared.price_utils import calculate_sell_price


def generate_new_items_excel(
    line_items: List[LineItem],
    supplier_code: str,
    output_path: str
) -> str:
    """
    Generate an Excel file for new items in the required format.
    
    Args:
        line_items: List of LineItem objects for new items
        supplier_code: Internal supplier code (or "UNKNOWN")
        output_path: Path to save the Excel file
        
    Returns:
        Path to the generated Excel file
    """
    
    # Build data rows (deduplicated by barcode)
    data = []
    seen_barcodes = set()
    
    for item in line_items:
        barcode = str(item.barcode) if item.barcode else ""
        
        # Skip if we've already seen this barcode
        if barcode in seen_barcodes:
            continue
        seen_barcodes.add(barcode)
        
        # Calculate sell price using the .90 rounding logic
        sell_price = calculate_sell_price(item.final_net_price) if item.final_net_price else 0
        
        row = {
            'ברקוד': barcode,
            'שם פריט': item.description,
            'ברקוד 2': barcode,  # Copy of primary barcode
            'מכירה': sell_price,
            'עלות נטו': item.final_net_price,
            'מספר ספק': supplier_code,
        }
        data.append(row)
    
    df = pd.DataFrame(data)
    
    # Ensure correct column order
    cols_order = ['ברקוד', 'שם פריט', 'ברקוד 2', 'מכירה', 'עלות נטו', 'מספר ספק']
    
    if df.empty:
        df = pd.DataFrame(columns=cols_order)
    else:
        df = df[cols_order]
    
    # Save to Excel
    df.to_excel(output_path, index=False)
    print(f"New items Excel generated: {output_path} ({len(data)} unique items)")
    
    return output_path


def filter_new_items_from_order(
    order: ExtractedOrder,
    new_barcodes: List[str]
) -> List[LineItem]:
    """
    Filter order line items to only include those with new barcodes.
    
    Args:
        order: The extracted order
        new_barcodes: List of barcodes that are new (not in database)
        
    Returns:
        List of LineItem objects for new items only
    """
    new_barcode_set = set(str(b).strip() for b in new_barcodes)
    
    new_items = []
    for item in order.line_items:
        barcode = str(item.barcode).strip() if item.barcode else ""
        if barcode and barcode in new_barcode_set:
            new_items.append(item)
    
    return new_items
