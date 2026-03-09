from datetime import datetime
from typing import Any

from google.cloud import firestore

from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder

logger = get_logger(__name__)


def save_order_to_firestore(
    order: ExtractedOrder,
    source_file_uri: str,
    *,
    is_test: bool = False,
    metadata: dict[str, Any] | None = None,
    new_items_data: list[dict[str, Any]] | None = None,
) -> str:
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
        order_dict["updated_at"] = datetime.utcnow()
        order_dict["gcs_uri"] = source_file_uri
        order_dict["status"] = "EXTRACTED"
        order_dict["is_test"] = bool(is_test or order_dict.get("is_test", False))
        order_dict["line_items_count"] = len(order_dict.get("line_items", []) or [])
        order_dict["warnings_count"] = len(order_dict.get("warnings", []) or [])
        order_dict["has_warnings"] = bool(order_dict["warnings_count"])
        order_dict["is_unknown_supplier"] = str(order_dict.get("supplier_code", "")).upper() == "UNKNOWN"

        if new_items_data:
            order_dict["new_items"] = new_items_data

        if "ui_metadata" not in order_dict or not isinstance(order_dict["ui_metadata"], dict):
            order_dict["ui_metadata"] = {}

        metadata = metadata or {}
        for field in ("sender", "subject", "filename"):
            if metadata.get(field):
                order_dict["ui_metadata"][field] = metadata[field]

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
