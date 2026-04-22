"""
Durable email outbox for user-facing response emails.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from src.ingestion.gmail_utils import normalize_email_subject
from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

EMAIL_STATUS_PENDING = "PENDING_RETRY"
EMAIL_STATUS_SENT = "SENT"
EMAIL_STATUS_FAILED_PERMANENT = "FAILED_PERMANENT"
MAX_EMAIL_ATTEMPTS = 12


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_doc_id(event_id: str, email_type: str) -> str:
    raw = f"{event_id}_{email_type}".strip() or f"email_{_utc_now().timestamp()}"
    return re.sub(r"[/#?\\\s]+", "_", raw)[:1400]


def _requires_index_error(error: Exception) -> bool:
    return "requires an index" in str(error).lower()


def _next_attempt_at(attempts: int) -> datetime:
    delay_minutes = min(360, 15 * (2 ** max(attempts - 1, 0)))
    return _utc_now() + timedelta(minutes=delay_minutes)


class EmailOutboxService:
    """Firestore-backed queue for reply emails that must eventually be sent."""

    def __init__(self, firestore_client: firestore.Client | None = None):
        self._db = firestore_client or firestore.Client(project=settings.PROJECT_ID)
        self._collection = self._db.collection(settings.FIRESTORE_EMAIL_OUTBOX_COLLECTION)
        self._orders = self._db.collection(settings.FIRESTORE_ORDERS_COLLECTION)
        self._processing_events = self._db.collection(settings.FIRESTORE_PROCESSING_COLLECTION)

    def enqueue_email(
        self,
        *,
        event_id: str,
        email_type: str,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False,
        attachment_refs: list[dict[str, Any]] | None = None,
        order_ids: list[str] | None = None,
        failed_order_id: str | None = None,
    ) -> str | None:
        if not event_id:
            logger.error("Cannot enqueue response email without event_id.")
            return None

        outbox_id = _safe_doc_id(event_id, email_type)
        doc_ref = self._collection.document(outbox_id)
        now = _utc_now()

        existing = doc_ref.get()
        existing_data = existing.to_dict() if existing.exists else {}
        if existing_data and existing_data.get("status") == EMAIL_STATUS_SENT:
            return outbox_id

        payload = {
            "event_id": str(event_id),
            "email_type": str(email_type).upper(),
            "status": existing_data.get("status") or EMAIL_STATUS_PENDING,
            "thread_id": thread_id,
            "message_id": message_id,
            "to": to,
            "subject": normalize_email_subject(subject),
            "body": body,
            "is_html": bool(is_html),
            "attachment_refs": attachment_refs or [],
            "order_ids": [str(order_id) for order_id in (order_ids or []) if order_id],
            "failed_order_id": failed_order_id,
            "attempt_count": int(existing_data.get("attempt_count") or 0),
            "max_attempts": int(existing_data.get("max_attempts") or MAX_EMAIL_ATTEMPTS),
            "next_attempt_at": existing_data.get("next_attempt_at") or now,
            "updated_at": now,
        }
        if not existing.exists:
            payload["created_at"] = now

        try:
            doc_ref.set(payload, merge=True)
            logger.info(f"Queued {email_type} response email {outbox_id} for event {event_id}")
            return outbox_id
        except Exception as e:
            logger.error(f"Failed enqueueing response email for event {event_id}: {e}")
            return None

    def get_email(self, outbox_id: str) -> dict | None:
        if not outbox_id:
            return None
        doc = self._collection.document(str(outbox_id)).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["outbox_id"] = doc.id
        return data

    def list_due_emails(self, limit: int = 50) -> list[dict]:
        now = _utc_now()
        try:
            docs = (
                self._collection.where(filter=FieldFilter("status", "==", EMAIL_STATUS_PENDING))
                .where(filter=FieldFilter("next_attempt_at", "<=", now))
                .order_by("next_attempt_at", direction=firestore.Query.ASCENDING)
                .limit(limit)
                .stream()
            )
            due: list[dict] = []
            for doc in docs:
                data = doc.to_dict() or {}
                data["outbox_id"] = doc.id
                due.append(data)
            return sorted(due, key=lambda item: _normalize_dt(item.get("next_attempt_at")) or now)
        except Exception as e:
            if not _requires_index_error(e):
                raise
            logger.warning("Firestore index for due email outbox is missing. Falling back to unindexed outbox scan.")

        docs = self._collection.where(filter=FieldFilter("status", "==", EMAIL_STATUS_PENDING)).stream()
        due: list[dict] = []
        for doc in docs:
            data = doc.to_dict() or {}
            next_attempt = _normalize_dt(data.get("next_attempt_at"))
            if next_attempt and next_attempt > now:
                continue
            data["outbox_id"] = doc.id
            due.append(data)
        return sorted(due, key=lambda item: _normalize_dt(item.get("next_attempt_at")) or now)[:limit]

    def mark_sent(self, outbox_id: str, *, attempts: int | None = None) -> bool:
        email = self.get_email(outbox_id)
        if not email:
            return False

        now = _utc_now()
        final_attempts = int(attempts if attempts is not None else email.get("attempt_count") or 0)
        payload = {
            "status": EMAIL_STATUS_SENT,
            "attempt_count": final_attempts,
            "sent_at": now,
            "updated_at": now,
            "next_attempt_at": None,
            "last_error": None,
        }
        try:
            self._collection.document(outbox_id).set(payload, merge=True)
            self._update_related_email_state(email, EMAIL_STATUS_SENT, final_attempts)
            return True
        except Exception as e:
            logger.error(f"Failed marking outbox email {outbox_id} sent: {e}")
            return False

    def mark_retry(self, outbox_id: str, *, attempts: int, last_error: str | None = None) -> str:
        email = self.get_email(outbox_id)
        if not email:
            return EMAIL_STATUS_FAILED_PERMANENT

        max_attempts = int(email.get("max_attempts") or MAX_EMAIL_ATTEMPTS)
        status = EMAIL_STATUS_FAILED_PERMANENT if attempts >= max_attempts else EMAIL_STATUS_PENDING
        payload = {
            "status": status,
            "attempt_count": int(attempts),
            "last_attempt_at": _utc_now(),
            "updated_at": _utc_now(),
            "last_error": (last_error or "Email send failed")[:2000],
        }
        if status == EMAIL_STATUS_PENDING:
            payload["next_attempt_at"] = _next_attempt_at(attempts)
        else:
            payload["next_attempt_at"] = None

        try:
            self._collection.document(outbox_id).set(payload, merge=True)
            self._update_related_email_state(email, status, attempts, last_error=last_error)
        except Exception as e:
            logger.error(f"Failed marking outbox email {outbox_id} retry: {e}")
        return status

    def mark_failed_permanent(self, outbox_id: str, *, attempts: int, last_error: str | None = None) -> bool:
        email = self.get_email(outbox_id)
        if not email:
            return False

        now = _utc_now()
        payload = {
            "status": EMAIL_STATUS_FAILED_PERMANENT,
            "attempt_count": int(attempts),
            "last_attempt_at": now,
            "updated_at": now,
            "next_attempt_at": None,
            "last_error": (last_error or "Permanent email send failure")[:2000],
        }
        try:
            self._collection.document(outbox_id).set(payload, merge=True)
            self._update_related_email_state(
                email,
                EMAIL_STATUS_FAILED_PERMANENT,
                attempts,
                last_error=last_error,
            )
            return True
        except Exception as e:
            logger.error(f"Failed marking outbox email {outbox_id} permanent failure: {e}")
            return False

    def mark_waiting(self, outbox_id: str, *, last_error: str) -> bool:
        email = self.get_email(outbox_id)
        try:
            self._collection.document(outbox_id).set(
                {
                    "status": EMAIL_STATUS_PENDING,
                    "last_error": last_error[:2000],
                    "updated_at": _utc_now(),
                    "next_attempt_at": _next_attempt_at(1),
                },
                merge=True,
            )
            if email:
                self._update_related_email_state(
                    email,
                    EMAIL_STATUS_PENDING,
                    int(email.get("attempt_count") or 0),
                    last_error=last_error,
                )
            return True
        except Exception as e:
            logger.error(f"Failed marking outbox email {outbox_id} waiting: {e}")
            return False

    def _update_related_email_state(
        self,
        email: dict,
        status: str,
        attempts: int,
        *,
        last_error: str | None = None,
    ) -> None:
        now = _utc_now()
        state = {
            "response_email_status": status,
            "response_email_attempts": int(attempts),
            "response_email_updated_at": now,
        }
        if last_error:
            state["response_email_last_error"] = last_error[:2000]
        elif status == EMAIL_STATUS_SENT:
            state["response_email_last_error"] = None
        if status == EMAIL_STATUS_SENT:
            state["response_email_sent_at"] = now

        event_id = email.get("event_id")
        if event_id:
            details = {
                **state,
                "response_email_outbox_id": email.get("outbox_id"),
                "feedback_email_status": status,
                "feedback_email_attempts": int(attempts),
            }
            if last_error:
                details["feedback_email_last_error"] = last_error[:2000]
            elif status == EMAIL_STATUS_SENT:
                details["feedback_email_last_error"] = None
            try:
                self._processing_events.document(str(event_id)).set(
                    {"details": details, "updated_at": now},
                    merge=True,
                )
            except Exception as e:
                logger.error(f"Failed updating processing event email state {event_id}: {e}")

        order_ids = [str(order_id) for order_id in (email.get("order_ids") or []) if order_id]
        failed_order_id = email.get("failed_order_id")
        if failed_order_id:
            order_ids.append(str(failed_order_id))
            state["feedback_email_status"] = status
            state["feedback_email_attempts"] = int(attempts)

        for order_id in set(order_ids):
            try:
                payload = dict(state)
                if failed_order_id and str(order_id) == str(failed_order_id):
                    ui_metadata = {
                        "feedback_email_status": status,
                        "feedback_email_attempts": int(attempts),
                    }
                    if last_error:
                        ui_metadata["feedback_email_last_error"] = last_error[:2000]
                    elif status == EMAIL_STATUS_SENT:
                        ui_metadata["feedback_email_last_error"] = None
                    payload["ui_metadata"] = ui_metadata
                self._orders.document(order_id).set(payload, merge=True)
            except Exception as e:
                logger.error(f"Failed updating order email state {order_id}: {e}")
