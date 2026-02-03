import pandas as pd
from typing import List
import os
import sys

# Add project root to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.models import ExtractedOrder, LineItem
from src.data.items_service import ItemsService

def _clean_str(val) -> str:
    """Helper to remove .0 from float-like strings and return empty string if None"""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() == 'nan' or s == 'None' or not s:
        return ""
    if s.endswith('.0'):
        return s[:-2]
    return s

def generate_excel_from_order(order: ExtractedOrder, output_path: str):
    """
    Converts an ExtractedOrder object into a Hebrew Excel file.
    Target Columns: ['קוד פריט', 'כמות', 'מחיר נטו']
    (Item Code, Quantity, Net Price)
    """
    
    items_service = ItemsService()
    
    # Transform data to list of dicts
    data = []
    
    # We might want to optimize this with a batch get if possible, but loop is fine for typical order sizes
    for item in order.line_items:
        barcode = str(item.barcode).strip() if item.barcode else ""
        item_code_val = barcode # Default to barcode
        
        if barcode:
            # Try to find existing item to get the real item_code
            # search_items checks for exact match on document ID (barcode) first
            results = items_service.search_items(barcode)
            if results:
                # Assuming the exact match is the first one or the one with matching barcode
                for res in results:
                    if str(res.get('barcode')) == barcode:
                        db_code = res.get('item_code')
                        if db_code:
                            item_code_val = db_code
                        break
        
        row = {
            'קוד פריט': _clean_str(item_code_val),
            'כמות': item.quantity,
            'מחיר נטו': item.final_net_price
        }
        data.append(row)
        
    df = pd.DataFrame(data)
    
    # Ensure correct column order
    cols_order = ['קוד פריט', 'כמות', 'מחיר נטו']
    
    # Handle case where no items extracted but we still want headers
    if df.empty:
        df = pd.DataFrame(columns=cols_order)
    else:
        # Ensure 'קוד פריט' exists even if data was empty loop
        if 'קוד פריט' not in df.columns:
            df['קוד פריט'] = None
        df = df[cols_order]
        
    # Save to Excel
    try:
        df.to_excel(output_path, index=False)
        print(f"Excel file successfully generated at: {output_path}")
    except Exception as e:
        print(f"Error generating Excel: {e}")
