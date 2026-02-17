from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class EmailMetadata(BaseModel):
    """Metadata about the source email."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_at: datetime = Field(default_factory=datetime.utcnow)
    body_snippet: str | None = None


class OrderIngestedEvent(BaseModel):
    """
    Event published when an email attachment is uploaded to GCS
    and ready for processing.
    """

    gcs_uri: str
    bucket_name: str
    blob_name: str
    filename: str
    mime_type: str
    email_metadata: EmailMetadata

    # Traceability
    event_id: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    timestamp: datetime = Field(default_factory=datetime.utcnow)
