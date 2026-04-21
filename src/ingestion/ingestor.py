import base64
import os
import tempfile
import uuid

from google.cloud import pubsub_v1

from src.core.events import EmailMetadata, OrderIngestedEvent
from src.ingestion.gcs_writer import upload_to_gcs
from src.ingestion.gmail_utils import get_email_body, get_gmail_service, normalize_email_subject
from src.shared.config import settings
from src.shared.idempotency_service import IdempotencyService
from src.shared.logger import get_logger
from src.shared.utils import is_allowed_sender

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
                msg_ctx = f"[message_id={msg_id}] "
                lock_acquired = False

                try:
                    # Fetch full details
                    msg = service.users().messages().get(userId="me", id=msg_id).execute()

                    if "UNREAD" not in msg["labelIds"]:
                        continue

                    headers = msg["payload"]["headers"]
                    subject = normalize_email_subject(next((h["value"] for h in headers if h["name"] == "Subject"), ""))
                    thread_id = msg["threadId"]

                    # Safety Filter: Replies
                    if subject.lower().startswith("re:"):
                        logger.info(f"{msg_ctx}Skipping reply: {subject}")
                        continue

                    # Extract Sender
                    sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")

                    if not is_allowed_sender(sender):
                        logger.info(f"{msg_ctx}Skipping sender not in ALLOWED_EMAILS: {sender}")
                        continue

                    # Ignore self
                    profile = service.users().getProfile(userId="me").execute()
                    my_email = profile["emailAddress"]
                    if my_email.lower() in sender.lower():
                        continue

                    logger.info(f"{msg_ctx}Ingesting email: {subject} from {sender}")
                    if not idempotency.check_and_lock_message(msg_id):
                        logger.info(f"{msg_ctx}Skipping message: already processed or locked.")
                        continue
                    lock_acquired = True

                    # Extract Body
                    email_body_text = get_email_body(msg["payload"])

                    # Find Attachments
                    parts = msg["payload"].get("parts", [])
                    found_attachments = []
                    from src.shared.utils import SUPPORTED_MIME_TYPES

                    for part in parts:
                        filename = part.get("filename", "")
                        if filename:
                            ext = os.path.splitext(filename.lower())[1]
                            if ext in SUPPORTED_MIME_TYPES:
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
                                    {"data": file_data, "filename": filename, "mime_type": SUPPORTED_MIME_TYPES[ext]}
                                )

                    if found_attachments:
                        all_published = True
                        for att in found_attachments:
                            # Generate a safe, UUID-based filename for storage and event
                            raw_original = os.path.basename(att["filename"]) or "attachment"
                            _, ext = os.path.splitext(raw_original.lower())
                            if not ext or not ext.startswith("."):
                                ext = ".bin"

                            safe_filename = f"{uuid.uuid4().hex}{ext}"

                            fd, temp_path = tempfile.mkstemp(prefix="ingest_", suffix=ext)
                            with os.fdopen(fd, "wb") as f:
                                f.write(att["data"])

                            try:
                                gcs_uri = upload_to_gcs(temp_path, safe_filename)
                                if not gcs_uri:
                                    logger.error(f"{msg_ctx}Failed to upload {safe_filename} to GCS. Skipping event.")
                                    all_published = False
                                    continue

                                email_meta = EmailMetadata(
                                    message_id=msg_id,
                                    thread_id=thread_id,
                                    sender=sender,
                                    subject=subject,
                                    body_snippet=email_body_text[:1000] if email_body_text else "",
                                )
                                event = OrderIngestedEvent(
                                    gcs_uri=gcs_uri,
                                    bucket_name=settings.GCS_BUCKET_NAME,
                                    blob_name=gcs_uri.replace(f"gs://{settings.GCS_BUCKET_NAME}/", ""),
                                    filename=safe_filename,
                                    mime_type=att["mime_type"],
                                    email_metadata=email_meta,
                                )
                                if not self.publish_event(event):
                                    all_published = False
                            except Exception as e:
                                logger.error(f"{msg_ctx}Error ingesting attachment {safe_filename}: {e}")
                                all_published = False
                            finally:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)

                        if all_published:
                            service.users().messages().modify(
                                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
                            ).execute()
                            processed_count += 1
                            idempotency.mark_message_completed(msg_id, success=True)
                        else:
                            logger.warning(f"{msg_ctx}Keeping message unread due to partial/failed publish.")
                            idempotency.mark_message_completed(
                                msg_id,
                                success=False,
                                error_message="One or more attachments failed to upload/publish",
                            )
                    else:
                        logger.info("No supported attachments.")
                        service.users().messages().modify(
                            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
                        ).execute()
                        idempotency.mark_message_completed(msg_id, success=True)

                except Exception as msg_err:
                    logger.error(f"{msg_ctx}Error while processing message: {msg_err}", exc_info=True)
                    if lock_acquired:
                        idempotency.mark_message_completed(msg_id, success=False, error_message=str(msg_err))
                    continue

            return processed_count

        except Exception as e:
            logger.error(f"Error in async ingestion: {e}", exc_info=True)
            return 0
