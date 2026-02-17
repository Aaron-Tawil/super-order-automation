import os
from datetime import datetime

from google.cloud import firestore

from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder

logger = get_logger(__name__)


def save_order_to_firestore(order: ExtractedOrder, source_file_uri: str) -> str:
    """
    Saves the extracted order to Firestore.
    Returns the document ID.
    """
    try:
        db = firestore.Client(project=settings.PROJECT_ID)
        collection_ref = db.collection(settings.FIRESTORE_ORDERS_COLLECTION)

        # Convert Pydantic to Dict
        order_dict = order.model_dump()

        # Add metadata
        order_dict["created_at"] = datetime.utcnow()
        order_dict["gcs_uri"] = source_file_uri
        order_dict["status"] = "EXTRACTED"

        # Create a new document
        doc_ref = collection_ref.document()  # Auto-generate ID
        doc_ref.set(order_dict)

        logger.info(f"Saved order {order.invoice_number} to Firestore with ID: {doc_ref.id}")
        return doc_ref.id

    except Exception as e:
        logger.error(f"Failed to save to Firestore: {e}")
        return None
