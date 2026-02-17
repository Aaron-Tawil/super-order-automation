"""
Utility script to delete items from Firestore for testing purposes.

Usage:
    # Delete specific barcodes
    python scripts/delete_items.py --barcodes 7291074033183 7291074034517

    # Delete barcodes from Excel file (expects column named 'barcode' or first column)
    python scripts/delete_items.py --excel test_barcodes.xlsx

    # Dry run (preview what would be deleted)
    python scripts/delete_items.py --barcodes 7291074033183 --dry-run
"""

import argparse
import os
import sys

import pandas as pd
from google.cloud import firestore

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

COLLECTION_NAME = "items"


def delete_barcodes(barcodes: list, dry_run: bool = False):
    """Delete items by barcode from Firestore."""

    if dry_run:
        print("DRY RUN - No data will be deleted from Firestore")
        print(f"Would delete {len(barcodes)} items:")
        for bc in barcodes[:20]:  # Show first 20
            print(f"  - {bc}")
        if len(barcodes) > 20:
            print(f"  ... and {len(barcodes) - 20} more")
        return

    db = firestore.Client()
    collection = db.collection(COLLECTION_NAME)

    deleted_count = 0
    not_found_count = 0

    for barcode in barcodes:
        barcode = str(barcode).strip()
        doc_ref = collection.document(barcode)
        doc = doc_ref.get()

        if doc.exists:
            doc_ref.delete()
            print(f"  Deleted: {barcode}")
            deleted_count += 1
        else:
            print(f"  Not found: {barcode}")
            not_found_count += 1

    print("\n[OK] Deletion complete!")
    print(f"   Deleted: {deleted_count}")
    print(f"   Not found: {not_found_count}")


def clean_barcode(val):
    """Clean barcode from potential internal ID prefix."""
    val = str(val).strip()
    parts = val.split()

    # If we successfully split by space
    if len(parts) > 1:
        for part in parts:
            if len(part) >= 12 and part.isdigit():
                return part

    # If no split or no valid part found in split, check if it's a concatenated string
    if len(val) > 14 and val.isdigit():
        # Assume it's [ID][BARCODE], take last 13 digits (standard EAN-13)
        return val[-13:]

    return val


def load_barcodes_from_excel(excel_path: str) -> list:
    """Load barcodes from Excel file."""
    df = pd.read_excel(excel_path)

    # Try to find barcode column
    barcode_col = None
    for col in df.columns:
        if "barcode" in str(col).lower() or "ברקוד" in str(col):
            barcode_col = col
            break

    if barcode_col is None:
        # Use first column
        barcode_col = df.columns[0]
        print(f"[INFO] Using first column '{barcode_col}' as barcode column")
    else:
        print(f"[INFO] Found barcode column: '{barcode_col}'")

    # Get values and clean them
    raw_values = df[barcode_col].dropna().astype(str).tolist()
    barcodes = [clean_barcode(v) for v in raw_values]

    print(f"[INFO] Loaded {len(barcodes)} barcodes from Excel")
    return barcodes


def main():
    parser = argparse.ArgumentParser(description="Delete items from Firestore by barcode")
    parser.add_argument("--barcodes", nargs="+", help="Barcodes to delete")
    parser.add_argument("--excel", help="Excel file with barcodes to delete")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    args = parser.parse_args()

    if not args.barcodes and not args.excel:
        print("[ERROR] Must provide either --barcodes or --excel")
        parser.print_help()
        sys.exit(1)

    barcodes = []

    if args.barcodes:
        barcodes.extend(args.barcodes)

    if args.excel:
        if not os.path.exists(args.excel):
            print(f"[ERROR] Excel file not found: {args.excel}")
            sys.exit(1)
        barcodes.extend(load_barcodes_from_excel(args.excel))

    if not barcodes:
        print("[ERROR] No barcodes provided")
        sys.exit(1)

    print(f"\n[INFO] Deleting {len(barcodes)} items from Firestore...")
    delete_barcodes(barcodes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
