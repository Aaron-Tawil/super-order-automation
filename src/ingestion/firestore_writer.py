from datetime import datetime
from typing import Any

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


def upsert_processing_event(
    event_id: str,
    *,
    status: str,
    stage: str,
    details: dict[str, Any] | None = None,
) -> bool:
    """
    Upsert processing lifecycle state for a single ingestion/processing event.
    """
    if not event_id:
        logger.error("Cannot upsert processing event without event_id.")
        return False

    try:
        db = firestore.Client(project=settings.PROJECT_ID)
        collection_ref = db.collection(settings.FIRESTORE_PROCESSING_COLLECTION)
        doc_ref = collection_ref.document(str(event_id))

        payload = {
            "event_id": str(event_id),
            "status": status,
            "stage": stage,
            "updated_at": datetime.utcnow(),
        }
        if details:
            payload["details"] = details

        existing = doc_ref.get()
        if not existing.exists:
            payload["created_at"] = datetime.utcnow()

        doc_ref.set(payload, merge=True)
        logger.info(f"Processing event {event_id} -> {status}/{stage}")
        return True
    except Exception as e:
        logger.error(f"Failed to upsert processing event {event_id}: {e}")
        return False
