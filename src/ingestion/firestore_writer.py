from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from src.shared.config import settings
from src.shared.constants import INGESTION_SOURCE_DASHBOARD_UPLOAD, INGESTION_SOURCE_EMAIL
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder
from src.shared.utils import extract_sender_email

logger = get_logger(__name__)


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _normalize_ingestion_source(metadata: dict[str, Any]) -> str | None:
    """Map caller metadata into a stable persisted ingestion source value."""
    raw_source = str(metadata.get("ingestion_source") or "").strip().lower()
    if raw_source in {INGESTION_SOURCE_EMAIL, INGESTION_SOURCE_DASHBOARD_UPLOAD}:
        return raw_source
    if metadata.get("from_manual_upload"):
        return INGESTION_SOURCE_DASHBOARD_UPLOAD
    return None


def save_order_to_firestore(
    order: ExtractedOrder,
    source_file_uri: str,
    *,
    is_test: bool = False,
    metadata: dict[str, Any] | None = None,
    new_items_data: list[dict[str, Any]] | None = None,
    added_items_barcodes: list[str] | None = None,
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
        order_dict["created_at"] = _utc_now()
        order_dict["updated_at"] = _utc_now()
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
        ingestion_source = _normalize_ingestion_source(metadata)
        sender_email = str(metadata.get("sender_email") or "").strip().lower()
        if not sender_email and ingestion_source == INGESTION_SOURCE_EMAIL:
            sender_email = extract_sender_email(metadata.get("sender"))

        if ingestion_source:
            order_dict["ingestion_source"] = ingestion_source
            order_dict["ui_metadata"]["ingestion_source"] = ingestion_source

        for field in ("sender", "subject", "filename"):
            if metadata.get(field):
                order_dict["ui_metadata"][field] = metadata[field]

        if sender_email:
            order_dict["sender_email"] = sender_email
            order_dict["ui_metadata"]["sender_email"] = sender_email

        if added_items_barcodes:
            order_dict["ui_metadata"]["added_items_barcodes"] = [
                str(barcode).strip() for barcode in added_items_barcodes if str(barcode).strip()
            ]

        # Create a new document
        doc_ref = collection_ref.document()  # Auto-generate ID
        doc_ref.set(order_dict)

        logger.info(f"Saved order {order.invoice_number} to Firestore with ID: {doc_ref.id}")
        return doc_ref.id

    except Exception as e:
        logger.error(f"Failed to save to Firestore: {e}")
        return None


def save_failed_order_to_firestore(
    *,
    event_id: str,
    source_file_uri: str,
    filename: str,
    sender: str,
    subject: str,
    message_id: str,
    thread_id: str,
    error: str,
    stage: str = "EXTRACTION",
    supplier_code: str | None = None,
    supplier_name: str | None = None,
    is_test: bool = False,
    feedback_email_status: str | None = None,
    feedback_email_attempts: int | None = None,
    ingestion_source: str = INGESTION_SOURCE_EMAIL,
    sender_email: str | None = None,
) -> str | None:
    """
    Persist a failed extraction placeholder in the orders collection.
    This keeps failed submissions visible in the same operational inbox as completed orders.
    """
    try:
        db = firestore.Client(project=settings.PROJECT_ID)
        collection_ref = db.collection(settings.FIRESTORE_ORDERS_COLLECTION)
        now = _utc_now()
        resolved_supplier_code = supplier_code or "UNKNOWN"

        doc = {
            "created_at": now,
            "updated_at": now,
            "gcs_uri": source_file_uri,
            "status": "FAILED",
            "stage": stage,
            "event_id": str(event_id),
            "is_failed_placeholder": True,
            "is_test": bool(is_test),
            "invoice_number": None,
            "currency": "ILS",
            "supplier_code": resolved_supplier_code,
            "supplier_name": supplier_name,
            "line_items": [],
            "line_items_count": 0,
            "warnings": [error] if error else [],
            "warnings_count": 1 if error else 0,
            "has_warnings": bool(error),
            "is_unknown_supplier": str(resolved_supplier_code).upper() == "UNKNOWN",
            "ingestion_source": ingestion_source,
            "sender": sender,
            "sender_email": sender_email or extract_sender_email(sender),
            "subject": subject,
            "filename": filename,
            "error": error,
            "feedback_email_status": feedback_email_status,
            "feedback_email_attempts": int(feedback_email_attempts or 0),
            "ui_metadata": {
                "sender": sender,
                "sender_email": sender_email or extract_sender_email(sender),
                "subject": subject,
                "filename": filename,
                "ingestion_source": ingestion_source,
                "source_file_uri": source_file_uri,
                "message_id": message_id,
                "thread_id": thread_id,
                "event_id": str(event_id),
                "error": error,
                "stage": stage,
                "feedback_email_status": feedback_email_status,
                "feedback_email_attempts": int(feedback_email_attempts or 0),
            },
        }

        doc_ref = collection_ref.document()
        doc_ref.set(doc)
        logger.info(f"Saved failed order placeholder for event {event_id} with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        logger.error(f"Failed to save failed order placeholder: {e}")
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
            "updated_at": _utc_now(),
        }
        if details:
            payload["details"] = details

        existing = doc_ref.get()
        if not existing.exists:
            payload["created_at"] = _utc_now()

        doc_ref.set(payload, merge=True)
        logger.info(f"Processing event {event_id} -> {status}/{stage}")
        return True
    except Exception as e:
        logger.error(f"Failed to upsert processing event {event_id}: {e}")
        return False
