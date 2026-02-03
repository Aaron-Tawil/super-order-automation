from google.cloud import firestore
import os
from datetime import datetime
from src.shared.models import ExtractedOrder

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")
COLLECTION_NAME = "orders"

def save_order_to_firestore(order: ExtractedOrder, gcs_uri: str) -> str:
    """
    Saves the extracted order to Firestore and returns the Document ID.
    """
    try:
        db = firestore.Client(project=PROJECT_ID)
        
        # Convert Pydantic to Dict
        order_dict = order.model_dump()
        
        # Add metadata
        order_dict["created_at"] = datetime.utcnow()
        order_dict["gcs_uri"] = gcs_uri
        order_dict["status"] = "EXTRACTED"
        
        # Create a new document
        update_time, doc_ref = db.collection(COLLECTION_NAME).add(order_dict)
        
        print(f"Saved order to Firestore: {doc_ref.id}")
        return doc_ref.id
        
    except Exception as e:
        print(f"Failed to save to Firestore: {e}")
        return None
