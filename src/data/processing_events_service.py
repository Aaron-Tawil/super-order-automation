"""
Read and update processing lifecycle events.
"""

from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)
MIN_DT = datetime.min.replace(tzinfo=UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_dt(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _requires_index_error(error: Exception) -> bool:
    return "requires an index" in str(error).lower()


class ProcessingEventsService:
    """Service for failed processing events shown in the dashboard and email retry flow."""

    def __init__(self, firestore_client: firestore.Client | None = None):
        self._db = firestore_client or firestore.Client(project=settings.PROJECT_ID)
        self._collection = self._db.collection(settings.FIRESTORE_PROCESSING_COLLECTION)

    def list_failed_events(self, limit: int = 500) -> list[dict]:
        try:
            docs = (
                self._collection.where(filter=FieldFilter("status", "==", "FAILED"))
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            events = [self._normalize_event_doc(doc.id, doc.to_dict() or {}) for doc in docs]
            return sorted(events, key=lambda e: e.get("created_at") or e.get("updated_at") or MIN_DT, reverse=True)
        except Exception as e:
            if not _requires_index_error(e):
                raise
            logger.warning(
                "Firestore index for failed processing events is missing. Falling back to unindexed failed-event scan."
            )

        docs = self._collection.where(filter=FieldFilter("status", "==", "FAILED")).stream()
        events = [self._normalize_event_doc(doc.id, doc.to_dict() or {}) for doc in docs]
        return sorted(events, key=lambda e: e.get("created_at") or e.get("updated_at") or MIN_DT, reverse=True)[:limit]

    def list_pending_feedback_email_events(self, limit: int = 50) -> list[dict]:
        try:
            docs = (
                self._collection.where(filter=FieldFilter("status", "==", "FAILED"))
                .where(filter=FieldFilter("details.feedback_email_status", "==", "PENDING_RETRY"))
                .limit(limit)
                .stream()
            )
            return [self._normalize_event_doc(doc.id, doc.to_dict() or {}) for doc in docs]
        except Exception as e:
            if not _requires_index_error(e):
                raise
            logger.warning(
                "Firestore index for pending failed feedback events is missing. "
                "Falling back to unindexed failed-event scan."
            )

        docs = self._collection.where(filter=FieldFilter("status", "==", "FAILED")).stream()
        events = [
            self._normalize_event_doc(doc.id, doc.to_dict() or {})
            for doc in docs
            if ((doc.to_dict() or {}).get("details") or {}).get("feedback_email_status") == "PENDING_RETRY"
        ]
        return sorted(events, key=lambda e: e.get("updated_at") or e.get("created_at") or MIN_DT, reverse=True)[:limit]

    def get_event(self, event_id: str) -> dict | None:
        if not event_id:
            return None
        doc = self._collection.document(str(event_id)).get()
        if not doc.exists:
            return None
        return self._normalize_event_doc(doc.id, doc.to_dict() or {})

    def update_feedback_email_state(
        self,
        event_id: str,
        *,
        status: str,
        attempts: int,
        last_error: str | None = None,
    ) -> bool:
        if not event_id:
            return False

        payload = {
            "details": {
                "feedback_email_status": status,
                "feedback_email_attempts": attempts,
                "feedback_email_last_attempt_at": _utc_now(),
            },
            "updated_at": _utc_now(),
        }
        if last_error:
            payload["details"]["feedback_email_last_error"] = last_error[:2000]

        try:
            self._collection.document(str(event_id)).set(payload, merge=True)
            return True
        except Exception as e:
            logger.error(f"Failed updating feedback email state for event {event_id}: {e}")
            return False

    def _normalize_event_doc(self, doc_id: str, data: dict) -> dict:
        details = data.get("details") if isinstance(data.get("details"), dict) else {}
        created_at = _normalize_dt(data.get("created_at") or data.get("updated_at"))
        updated_at = _normalize_dt(data.get("updated_at"))

        event = {
            "event_id": str(data.get("event_id") or doc_id),
            "order_id": None,
            "record_type": "processing_event",
            "status": data.get("status", "UNKNOWN"),
            "stage": data.get("stage"),
            "created_at": created_at,
            "updated_at": updated_at,
            "supplier_code": details.get("supplier_code") or "UNKNOWN",
            "supplier_name": details.get("supplier_name"),
            "invoice_number": details.get("invoice_number") or "-",
            "sender": details.get("sender") or "-",
            "subject": details.get("subject") or "-",
            "filename": details.get("filename") or "-",
            "gcs_uri": details.get("gcs_uri"),
            "message_id": details.get("message_id"),
            "thread_id": details.get("thread_id"),
            "error": details.get("error") or details.get("feedback_email_last_error") or "-",
            "feedback_email_status": details.get("response_email_status")
            or details.get("feedback_email_status")
            or "-",
            "feedback_email_attempts": int(
                details.get("response_email_attempts") or details.get("feedback_email_attempts") or 0
            ),
            "line_items": [],
            "line_items_count": 0,
            "warnings_count": 1 if details.get("error") else 0,
            "warnings": [details.get("error")] if details.get("error") else [],
            "is_test": bool(details.get("is_test", False)),
            "details": details,
        }
        return event
