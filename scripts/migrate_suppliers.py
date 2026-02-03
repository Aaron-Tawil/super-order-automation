"""
One-time migration script to load suppliers from Excel to Firestore.

Usage:
    python scripts/migrate_suppliers.py

Prerequisites:
    - Set GOOGLE_APPLICATION_CREDENTIALS environment variable
    - Or run: gcloud auth application-default login
"""

import pandas as pd
from google.cloud import firestore
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configuration
EXCEL_PATH = "data-excel/suppliers.xlsx"
COLLECTION_NAME = "suppliers"


def load_suppliers_from_excel(excel_path: str) -> pd.DataFrame:
    """Load suppliers from Excel."""
    df = pd.read_excel(excel_path)
    # Columns: קוד, שם, טלפון, Email, עוסק/ח"פ
    df.columns = ['supplier_code', 'name', 'phone', 'email', 'global_id']
    
    print(f"Loaded {len(df)} suppliers")
    return df


def migrate_to_firestore(df: pd.DataFrame, dry_run: bool = False):
    """Migrate suppliers to Firestore."""
    if dry_run:
        print("DRY RUN - No data will be written to Firestore")
        print(f"Would migrate {len(df)} suppliers")
        print("\nSample suppliers:")
        print(df.head(10))
        return
    
    db = firestore.Client()
    collection = db.collection(COLLECTION_NAME)
    
    batch = db.batch()
    batch_count = 0
    total_migrated = 0

    for _, row in df.iterrows():
        supplier_code = str(row['supplier_code']).strip()
        
        doc_ref = collection.document(supplier_code)
        
        # Clean up phone - convert to string
        phone = row['phone']
        if pd.notna(phone):
            phone = str(int(phone)) if isinstance(phone, float) else str(phone)
        else:
            phone = None
        
        # Clean up global_id - convert to string
        global_id = row['global_id']
        if pd.notna(global_id) and global_id != 0:
            global_id = str(int(global_id)) if isinstance(global_id, float) else str(global_id)
        else:
            global_id = None
            
        doc_data = {
            'name': str(row['name']) if pd.notna(row['name']) else None,
            'phone': phone,
            'email': str(row['email']).strip().lower() if pd.notna(row['email']) else None,
            'global_id': global_id,
        }
        
        batch.set(doc_ref, doc_data)
        batch_count += 1
        total_migrated += 1
        
        # Firestore batch limit is 500
        if batch_count >= 500:
            batch.commit()
            print(f"Committed batch: {total_migrated} suppliers migrated so far...")
            batch = db.batch()
            batch_count = 0
    
    # Commit remaining
    if batch_count > 0:
        batch.commit()
    
    print(f"\n[OK] Migration complete!")
    print(f"   Total suppliers migrated: {total_migrated}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Migrate suppliers Excel to Firestore')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing to Firestore')
    args = parser.parse_args()
    
    # Check if Excel exists
    if not os.path.exists(EXCEL_PATH):
        print(f"[ERROR] Excel file not found at {EXCEL_PATH}")
        sys.exit(1)
    
    print(f"[INFO] Loading suppliers from: {EXCEL_PATH}")
    df = load_suppliers_from_excel(EXCEL_PATH)
    
    print(f"\n[INFO] Migrating to Firestore collection: {COLLECTION_NAME}")
    migrate_to_firestore(df, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
