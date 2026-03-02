"""
Idempotency Service

Handles checking and locking of message IDs in Firestore to prevent
double-processing of the same email trigger.
"""

import os
from datetime import datetime, timedelta

from google.api_core import exceptions
from google.cloud import firestore

from src.shared.logger import get_logger

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")
COLLECTION_NAME = "processed_messages"
logger = get_logger(__name__)


def _normalize_dt(value):
    """Normalize Firestore datetimes for reliable utcnow comparisons."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if getattr(value, "tzinfo", None):
        value = value.replace(tzinfo=None)
    return value


def _get_db(project_id: str = PROJECT_ID):
    """Get Firestore client."""
    return firestore.Client(project=project_id)


class IdempotencyService:
    def __init__(self, collection_name: str = COLLECTION_NAME, project_id: str = PROJECT_ID):
        self.db = _get_db(project_id)
        self.collection = self.db.collection(collection_name)

    def check_and_lock_message(self, message_id: str, expiry_minutes: int = 60) -> bool:
        """
        Attempts to lock a message ID for processing.

        Args:
            message_id: The unique ID of the message (Gmail Message ID)
            expiry_minutes: How long the lock is valid for (default 60 mins)

        Returns:
            True if lock acquired (processing can proceed).
            False if already processed or currently locked.
        """
        if not message_id:
            return False

        doc_ref = self.collection.document(message_id)
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=expiry_minutes)

        try:
            current_doc = doc_ref.get()
            if not current_doc.exists:
                try:
                    doc_ref.create(
                        {
                            "status": "PROCESSING",
                            "created_at": now,
                            "expires_at": expires_at,
                            "processed_at": None,
                            "attempt_count": 1,
                        }
                    )
                    logger.info(f"Acquired lock for message {message_id}")
                    return True
                except exceptions.AlreadyExists:
                    logger.warning(f"Message {message_id} already locked by another worker.")
                    return False

            current = current_doc.to_dict() or {}
            status = str(current.get("status", "")).upper()
            current_expiry = _normalize_dt(current.get("expires_at"))
            active_lock = status == "PROCESSING" and current_expiry and current_expiry > now

            if status == "COMPLETED" or active_lock:
                logger.warning(f"Message {message_id} is already completed or actively processing.")
                return False

            attempts = int(current.get("attempt_count") or 0) + 1
            doc_ref.set(
                {
                    "status": "PROCESSING",
                    "created_at": current.get("created_at") or now,
                    "expires_at": expires_at,
                    "processed_at": None,
                    "attempt_count": attempts,
                },
                merge=True,
            )
            logger.info(f"Re-acquired lock for message {message_id} (attempt {attempts})")
            return True

        except Exception as e:
            if "Already Exists" in str(e) or "409" in str(e):
                logger.warning(f"Message {message_id} already exists (caught generic exception).")
                return False

            logger.error(f"Error locking message {message_id}: {e}")
            return False

    def mark_message_completed(self, message_id: str, success: bool = True, error_message: str | None = None):
        """
        Updates the status of the message to COMPLETED (or FAILED).
        """
        try:
            doc_ref = self.collection.document(message_id)
            payload = {
                "status": "COMPLETED" if success else "FAILED",
                "processed_at": datetime.utcnow(),
            }
            if error_message:
                payload["error_message"] = error_message[:2000]
            doc_ref.set(payload, merge=True)
            logger.info(f"Marked message {message_id} as {'COMPLETED' if success else 'FAILED'}")
        except Exception as e:
            logger.error(f"Failed to update message status {message_id}: {e}")
