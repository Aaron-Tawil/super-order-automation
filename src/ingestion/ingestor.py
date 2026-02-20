import base64
import json
import os
import uuid
from datetime import datetime
from typing import List, Optional

from google.cloud import pubsub_v1
from googleapiclient.discovery import build

from src.core.events import EmailMetadata, OrderIngestedEvent
from src.ingestion.gcs_writer import upload_to_gcs
from src.ingestion.gmail_utils import get_email_body, get_gmail_service
from src.shared.config import settings
from src.shared.idempotency_service import IdempotencyService
from src.shared.logger import get_logger

logger = get_logger(__name__)


class IngestionService:
    """
    Handles fetching emails, uploading attachments to GCS,
    and publishing events to Pub/Sub for asynchronous processing.
    """

    def __init__(self):
        self.project_id = settings.PROJECT_ID
        self.topic_id = "order-ingestion-topic"  # Should be in settings ideally
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_id)

    def publish_event(self, event: OrderIngestedEvent) -> str:
        """Publishes an ingestion event to Pub/Sub."""
        try:
            data_str = event.model_dump_json()
            data = data_str.encode("utf-8")

            future = self.publisher.publish(self.topic_path, data)
            message_id = future.result()

            logger.info(f"Published event {event.event_id} to {self.topic_path} (msg_id: {message_id})")
            return message_id
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            return None

    def process_unread_emails_async(self) -> int:
        """
        Scans for unread emails, uploads attachments, and publishes events.
        Does NOT perform extraction.
        Returns: Number of emails processed (ingested).
        """
        service = get_gmail_service()
        if not service:
            logger.error("Failed to get Gmail service.")
            return 0

        try:
            # Search for UNREAD emails with ATTACHMENTS
            # Same query as before
            results = (
                service.users()
                .messages()
                .list(userId="me", labelIds=["INBOX"], q="is:unread has:attachment", maxResults=10)
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                logger.info("No unread messages with attachments found.")
                return 0

            logger.info(f"Found {len(messages)} unread messages for ingestion.")
            processed_count = 0

            # Initialize Idempotency Service (reuse existing)
            idempotency = IdempotencyService()

            for msg_item in messages:
                msg_id = msg_item["id"]

                # === IDEMPOTENCY CHECK ===
                if not idempotency.check_and_lock_message(msg_id):
                    logger.info(f"Skipping message {msg_id}: Already processed or locked.")
                    continue

                try:
                    # Fetch full details
                    msg = service.users().messages().get(userId="me", id=msg_id).execute()
                except Exception as msg_err:
                    logger.error(f"Failed to fetch details for {msg_id}: {msg_err}")
                    continue

                if "UNREAD" not in msg["labelIds"]:
                    continue

                headers = msg["payload"]["headers"]
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
                thread_id = msg["threadId"]

                # Safety Filter: Replies
                if subject.lower().startswith("re:"):
                    logger.info(f"Skipping Reply: {subject}")
                    continue

                # Extract Sender
                sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")

                # Ignore self
                profile = service.users().getProfile(userId="me").execute()
                my_email = profile["emailAddress"]
                if my_email.lower() in sender.lower():
                    continue

                logger.info(f"Ingesting Email: {subject} from {sender}")

                # Mark as READ
                service.users().messages().modify(userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}).execute()

                # Extract Body
                email_body_text = get_email_body(msg["payload"])

                # Find Attachments
                parts = msg["payload"].get("parts", [])
                found_attachments = []
                SUPPORTED_EXTENSIONS = {
                    ".pdf": "application/pdf",
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".xls": "application/vnd.ms-excel",
                }

                for part in parts:
                    filename = part.get("filename", "")
                    if filename:
                        ext = os.path.splitext(filename.lower())[1]
                        if ext in SUPPORTED_EXTENSIONS:
                            # Get data
                            if "data" in part["body"]:
                                file_data = base64.urlsafe_b64decode(part["body"]["data"])
                            else:
                                att_id = part["body"]["attachmentId"]
                                att = (
                                    service.users()
                                    .messages()
                                    .attachments()
                                    .get(userId="me", messageId=msg_id, id=att_id)
                                    .execute()
                                )
                                file_data = base64.urlsafe_b64decode(att["data"])

                            found_attachments.append(
                                {"data": file_data, "filename": filename, "mime_type": SUPPORTED_EXTENSIONS[ext]}
                            )

                if found_attachments:
                    all_published = True
                    for att in found_attachments:
                        # 1. Upload to GCS
                        temp_path = f"/tmp/ingest_{att['filename']}" if os.name != "nt" else f"ingest_{att['filename']}"
                        with open(temp_path, "wb") as f:
                            f.write(att["data"])

                        try:
                            gcs_uri = upload_to_gcs(temp_path, att["filename"])
                            if not gcs_uri:
                                logger.error(f"Failed to upload {att['filename']} to GCS. Skipping event.")
                                all_published = False
                                continue

                            # 2. Build Metadata
                            email_meta = EmailMetadata(
                                message_id=msg_id,
                                thread_id=thread_id,
                                sender=sender,
                                subject=subject,
                                body_snippet=email_body_text[:1000] if email_body_text else "",
                            )

                            # 3. Create Event
                            event = OrderIngestedEvent(
                                gcs_uri=gcs_uri,
                                bucket_name=settings.GCS_BUCKET_NAME,
                                blob_name=gcs_uri.replace(f"gs://{settings.GCS_BUCKET_NAME}/", ""),
                                filename=att["filename"],
                                mime_type=att["mime_type"],
                                email_metadata=email_meta,
                            )

                            # 4. Publish
                            msg_id_pub = self.publish_event(event)
                            if not msg_id_pub:
                                all_published = False

                        except Exception as e:
                            logger.error(f"Error ingesting attachment {att['filename']}: {e}")
                            all_published = False
                        finally:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)

                    processed_count += 1
                    idempotency.mark_message_completed(msg_id, success=all_published)
                else:
                    logger.info("No supported attachments.")
                    idempotency.mark_message_completed(msg_id, success=True)

            return processed_count

        except Exception as e:
            logger.error(f"Error in async ingestion: {e}", exc_info=True)
            return 0
