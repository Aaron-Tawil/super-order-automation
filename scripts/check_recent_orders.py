import os
import sys
from datetime import datetime, timedelta

from google.cloud import firestore

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shared.config import settings


def check_orders():
    print(f"Checking collection: {settings.FIRESTORE_ORDERS_COLLECTION} in project: {settings.PROJECT_ID}")
    db = firestore.Client(project=settings.PROJECT_ID)
    
    # Check orders created in the last hour
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    orders = db.collection(settings.FIRESTORE_ORDERS_COLLECTION).where("created_at", ">", one_hour_ago).stream()
    
    count = 0
    for order in orders:
        count += 1
        data = order.to_dict()
        print(f"\nOrder ID: {order.id}")
        print(f"Invoice: {data.get('invoice_number')}")
        print(f"Supplier: {data.get('supplier_name')} ({data.get('supplier_code')})")
        print(f"Status: {data.get('status')}")
        print(f"Warnings: {len(data.get('warnings', []))}")
        for w in data.get('warnings', []):
            print(f"  - {w}")
            
    print(f"\nTotal recent orders found: {count}")

if __name__ == "__main__":
    check_orders()
