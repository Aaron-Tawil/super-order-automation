"""
Session Store for Super Order Automation

Firestore-based session store to share extracted order data between
the email processor (Cloud Functions) and the web UI (Cloud Run).
"""

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from google.cloud import firestore

from src.shared.config import settings

# Configuration
# PROJECT_ID = settings.PROJECT_ID # Handled in _get_db
# COLLECTION_NAME = settings.FIRESTORE_SESSIONS_COLLECTION # Handled in func


def _get_db():
    """Get Firestore client."""
    return firestore.Client(project=settings.PROJECT_ID)


def create_session(order, metadata: dict = None) -> str:
    """
    Create a new session in Firestore and return the session ID.

    Args:
        order: The extracted order data (ExtractedOrder object)
        metadata: Optional metadata (subject, sender, etc.)

    Returns:
        Session ID string (UUID)
    """
    try:
        db = _get_db()
        session_id = str(uuid.uuid4())

        # Convert order to dict if it's a Pydantic model
        order_data = order.model_dump() if hasattr(order, "model_dump") else order

        # Calculate expiry
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(hours=settings.SESSION_EXPIRY_HOURS)

        session_data = {
            "order": order_data,
            "metadata": metadata or {},
            "created_at": created_at,
            "expires_at": expires_at,
        }

        db.collection(settings.FIRESTORE_SESSIONS_COLLECTION).document(session_id).set(session_data)
        logging.info(f"Created session {session_id} in Firestore")
        return session_id

    except Exception as e:
        logging.error(f"Failed to create session in Firestore: {e}")
        # Build a fallback for local testing without creds if needed,
        # but for now we want to fail loudly if DB is missing.
        raise


def get_session(session_id: str) -> dict | None:
    """
    Retrieve a session by ID from Firestore.

    Returns None if the session is expired or not found.
    """
    if not session_id:
        return None

    try:
        db = _get_db()
        doc_ref = db.collection(settings.FIRESTORE_SESSIONS_COLLECTION).document(session_id)
        doc = doc_ref.get()

        if not doc.exists:
            logging.warning(f"Session {session_id} not found")
            return None

        session_data = doc.to_dict()

        # Check expiry
        expires_at = session_data.get("expires_at")
        # Firestore returns datetime with timezone info, or naive if stored that way.
        # Ensure comparison works.
        if expires_at:
            # If it's a string (legacy/fallback), parse it
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)

            # Make naive if needed to compare with utcnow
            if expires_at.tzinfo:
                expires_at = expires_at.replace(tzinfo=None)

            if datetime.utcnow() > expires_at:
                logging.warning(f"Session {session_id} expired")
                return None

        return session_data

    except Exception as e:
        logging.error(f"Failed to get session {session_id}: {e}")
        return None


def update_session_order(session_id: str, order) -> bool:
    """
    Update the order data in an existing session in Firestore.

    Returns True if successful, False if session not found.
    """
    try:
        db = _get_db()
        doc_ref = db.collection(settings.FIRESTORE_SESSIONS_COLLECTION).document(session_id)

        # Check existence first to avoid creating a new doc with just order data
        if not doc_ref.get().exists:
            return False

        order_data = order.model_dump() if hasattr(order, "model_dump") else order
        doc_ref.update({"order": order_data})
        logging.info(f"Updated session {session_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to update session {session_id}: {e}")
        return False


def get_session_count() -> int:
    """
    Return estimate of active sessions.
    Note: Exact count in Firestore can be expensive/slow for large collections.
    """
    try:
        db = _get_db()
        # Initial implementation: just count all (or use aggregation query if needed)
        # For low volume, retrieving all IDs is okay-ish, but aggregation is better.
        query = db.collection(settings.FIRESTORE_SESSIONS_COLLECTION).where(
            filter=firestore.FieldFilter("expires_at", ">", datetime.utcnow())
        )
        agg_query = query.count()
        return agg_query.get()[0][0].value
    except Exception as e:
        logging.error(f"Failed to count sessions: {e}")
        return 0


def update_session_metadata(session_id: str, metadata: dict) -> bool:
    """
    Update the metadata in an existing session in Firestore.
    """
    try:
        db = _get_db()
        doc_ref = db.collection(settings.FIRESTORE_SESSIONS_COLLECTION).document(session_id)

        if not doc_ref.get().exists:
            return False

        doc_ref.update({"metadata": metadata})
        logging.info(f"Updated session metadata {session_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to update session metadata {session_id}: {e}")
        return False
