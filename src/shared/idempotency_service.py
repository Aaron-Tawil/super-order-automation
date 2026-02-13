"""
Idempotency Service

Handles checking and locking of message IDs in Firestore to prevent 
double-processing of the same email trigger.
"""
import os
import logging
from datetime import datetime, timedelta
from google.cloud import firestore
from google.api_core import exceptions
from typing import Optional

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "super-home-automation")
COLLECTION_NAME = "processed_messages"

def _get_db():
    """Get Firestore client."""
    return firestore.Client(project=PROJECT_ID)

class IdempotencyService:
    def __init__(self):
        self.db = _get_db()
        self.collection = self.db.collection(COLLECTION_NAME)

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

        try:
            # Transactional check-and-set is best, but for simple idempotency 
            # `create` (which fails if exists) is sufficient and atomic.
            
            now = datetime.utcnow()
            expires_at = now + timedelta(minutes=expiry_minutes)
            
            # Try to create the document. This fails if it already exists.
            doc_ref.create({
                "status": "PROCESSING",
                "created_at": now,
                "expires_at": expires_at,
                "processed_at": None
            })
            
            logging.info(f"Acquired lock for message {message_id}")
            return True
            
        except exceptions.AlreadyExists:
             # Document already exists (409 Conflict)
            logging.warning(f"Message {message_id} is already being processed or finished.")
            return False
            
        except Exception as e:
            # Handle the case where 'headers' isn't available or other errors
            # If the error is essentially "Already Exists", return False.
            if "Already Exists" in str(e) or "409" in str(e):
                logging.warning(f"Message {message_id} already exists (caught generic exception).")
                return False
                
            logging.error(f"Error locking message {message_id}: {e}")
            # Fail closed (don't process) to be safe, or open? 
            # Safe = return False (don't process if DB is down)
            return False

    def mark_message_completed(self, message_id: str, success: bool = True):
        """
        Updates the status of the message to COMPLETED (or FAILED).
        """
        try:
            doc_ref = self.collection.document(message_id)
            doc_ref.update({
                "status": "COMPLETED" if success else "FAILED",
                "processed_at": datetime.utcnow()
            })
            logging.info(f"Marked message {message_id} as {'COMPLETED' if success else 'FAILED'}")
        except Exception as e:
            logging.error(f"Failed to update message status {message_id}: {e}")
