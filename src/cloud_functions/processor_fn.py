import base64
import json
import os
import re
import uuid
from typing import Any

import functions_framework
from pydantic import ValidationError

from src.core.events import OrderIngestedEvent
from src.data.email_outbox_service import (
    EMAIL_STATUS_FAILED_PERMANENT,
    EMAIL_STATUS_PENDING,
    EMAIL_STATUS_SENT,
    EmailOutboxService,
)
from src.data.items_service import ItemsService
from src.extraction.vertex_client import init_client
from src.ingestion.email_outbox_sender import OUTBOX_SEND_PERMANENT_FAILED, OUTBOX_SEND_SENT, send_outbox_email
from src.ingestion.firestore_writer import (
    save_failed_order_to_firestore,
    save_order_to_firestore,
    upsert_processing_event,
)
from src.ingestion.gcs_writer import download_file_from_gcs
from src.ingestion.gmail_utils import get_gmail_service, normalize_email_subject
from src.shared.config import settings
from src.shared.constants import INGESTION_SOURCE_EMAIL
from src.shared.idempotency_service import IdempotencyService
from src.shared.logger import get_logger
from src.shared.translations import get_text
from src.shared.utils import extract_sender_email, is_test_sender

logger = get_logger(__name__)


def _safe_temp_path(filename: str) -> str:
    """Build a collision-resistant temp path for downloaded source files using UUID for safety."""
    raw_name = os.path.basename((filename or "").strip())

    # Extract extension reliably
    _, ext = os.path.splitext(raw_name.lower())
    if not ext or not ext.startswith("."):
        # Fallback for cases where splitext might fail or extension is missing
        ext_match = re.search(r"(\.[A-Za-z0-9]{1,16})$", raw_name.lower())
        ext = ext_match.group(1) if ext_match else ".bin"

    unique_name = f"{uuid.uuid4().hex}{ext}"
    return f"/tmp/{unique_name}" if os.name != "nt" else f"temp_{unique_name}"


def _track_event_status(event_id: str, status: str, stage: str, details: dict | None = None) -> None:
    """Best-effort processing status persistence; never raises."""
    if not event_id:
        return
    upsert_processing_event(event_id, status=status, stage=stage, details=details or {})


def _event_details(
    event: OrderIngestedEvent,
    *,
    error: str | None = None,
    supplier_code: str | None = None,
    supplier_name: str | None = None,
    feedback_email_status: str | None = None,
    feedback_email_attempts: int | None = None,
    extra: dict | None = None,
) -> dict:
    """Build stable processing event details for dashboard visibility and retry."""
    details = {
        "filename": event.filename,
        "gcs_uri": event.gcs_uri,
        "sender": event.email_metadata.sender,
        "subject": normalize_email_subject(event.email_metadata.subject),
        "message_id": event.email_metadata.message_id,
        "thread_id": event.email_metadata.thread_id,
    }
    if error:
        details["error"] = error
    if supplier_code:
        details["supplier_code"] = supplier_code
    if supplier_name:
        details["supplier_name"] = supplier_name
    if feedback_email_status:
        details["feedback_email_status"] = feedback_email_status
    if feedback_email_attempts is not None:
        details["feedback_email_attempts"] = feedback_email_attempts
    if extra:
        details.update(extra)
    return details


def _queue_and_attempt_response_email(
    *,
    event_id: str,
    email_type: str,
    event: OrderIngestedEvent,
    body: str,
    is_html: bool,
    gmail_service,
    attachment_refs: list[dict] | None = None,
    order_ids: list[str] | None = None,
    failed_order_id: str | None = None,
) -> tuple[str, int, str | None]:
    """Queue a reply email, then make one immediate send attempt if Gmail is available."""
    outbox = EmailOutboxService()
    outbox_id = outbox.enqueue_email(
        event_id=event_id,
        email_type=email_type,
        thread_id=event.email_metadata.thread_id,
        message_id=event.email_metadata.message_id,
        to=event.email_metadata.sender,
        subject=normalize_email_subject(event.email_metadata.subject),
        body=body,
        is_html=is_html,
        attachment_refs=attachment_refs or [],
        order_ids=order_ids or [],
        failed_order_id=failed_order_id,
    )
    if not outbox_id:
        return EMAIL_STATUS_PENDING, 0, None

    email_doc = outbox.get_email(outbox_id)
    attempts = int((email_doc or {}).get("attempt_count") or 0)
    if not gmail_service or not email_doc:
        if email_doc:
            outbox.mark_waiting(outbox_id, last_error="Gmail service unavailable")
        return EMAIL_STATUS_PENDING, attempts, outbox_id

    existing_status = str(email_doc.get("status") or "").upper()
    if existing_status == EMAIL_STATUS_SENT:
        return EMAIL_STATUS_SENT, attempts, outbox_id
    if existing_status == EMAIL_STATUS_FAILED_PERMANENT:
        return EMAIL_STATUS_FAILED_PERMANENT, attempts, outbox_id

    send_status, error = send_outbox_email(email_doc, gmail_service)
    attempts += 1
    if send_status == OUTBOX_SEND_SENT:
        outbox.mark_sent(outbox_id, attempts=attempts)
        return EMAIL_STATUS_SENT, attempts, outbox_id

    if send_status == OUTBOX_SEND_PERMANENT_FAILED:
        outbox.mark_failed_permanent(outbox_id, attempts=attempts, last_error=error)
        return EMAIL_STATUS_FAILED_PERMANENT, attempts, outbox_id

    status = outbox.mark_retry(outbox_id, attempts=attempts, last_error=error)
    return status, attempts, outbox_id


def _ctx(event_id: str | None = None, message_id: str | None = None) -> str:
    parts = []
    if event_id:
        parts.append(f"event_id={event_id}")
    if message_id:
        parts.append(f"message_id={message_id}")
    return f"[{' '.join(parts)}] " if parts else ""


# Initialize Gemini Client once per cold start
try:
    init_client()
    logger.info("Gemini Client initialized for Cloud Function.")
except Exception as e:
    logger.error(f"Failed to initialize Gemini Client: {e}")


@functions_framework.cloud_event
def process_order_event(cloud_event: Any):
    """
    Cloud Function triggered by Pub/Sub when an email is ingested.
    Expected Payload: OrderIngestedEvent (JSON)
    """
    event = None
    gmail_service = None
    processing_lock = None
    temp_path = None
    event_id = str(getattr(cloud_event, "id", "unknown_event"))
    message_id = ""
    pubsub_message = ""

    try:
        # 1. Decode Pub/Sub Message
        pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
        logger.info(f"Received Pub/Sub message: {pubsub_message}")

        # 2. Parse Event
        try:
            event_data = json.loads(pubsub_message)
            event = OrderIngestedEvent(**event_data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Invalid event format: {e}")
            _track_event_status(
                event_id,
                status="FAILED",
                stage="PARSE_EVENT",
                details={"error": str(e), "raw_message": pubsub_message[:2000]},
            )
            return

        event_id = event.event_id or event_id
        message_id = event.email_metadata.message_id
        email_subject = normalize_email_subject(event.email_metadata.subject)
        sender_email = extract_sender_email(event.email_metadata.sender)
        ctx = _ctx(event_id, message_id)
        _track_event_status(
            event_id,
            status="PROCESSING",
            stage="RECEIVED",
            details=_event_details(event),
        )

        processing_lock = IdempotencyService(collection_name="processed_order_events")
        if not processing_lock.check_and_lock_message(event_id, expiry_minutes=180):
            logger.info(f"{ctx}Skipping duplicate/locked processing event")
            _track_event_status(
                event_id,
                status="SKIPPED",
                stage="DUPLICATE",
                details={"reason": "already_processing_or_completed"},
            )
            return

        logger.info("========================================================================")
        logger.info(f"{ctx}>>> STARTING ORDER PIPELINE (File: {event.filename})")
        logger.info("========================================================================")

        # 3. Download File
        temp_path = _safe_temp_path(event.filename)
        if not download_file_from_gcs(event.gcs_uri, temp_path):
            err_msg = f"Failed to download file from {event.gcs_uri}"
            logger.error(f"{ctx}{err_msg}")
            try:
                gmail_service = get_gmail_service()
            except Exception as gmail_err:
                logger.error(f"{ctx}Failed to initialize Gmail service for download failure reply: {gmail_err}")
                gmail_service = None
            email_status, email_attempts, outbox_id = _queue_and_attempt_response_email(
                event_id=event_id,
                email_type="FAILURE",
                event=event,
                body=get_text("email_err_body_prefix") + err_msg,
                is_html=False,
                gmail_service=gmail_service,
            )
            _track_event_status(
                event_id,
                status="FAILED",
                stage="DOWNLOAD",
                details=_event_details(
                    event,
                    error=err_msg,
                    feedback_email_status=email_status,
                    feedback_email_attempts=email_attempts,
                    extra={"response_email_outbox_id": outbox_id} if outbox_id else None,
                ),
            )
            processing_lock.mark_message_completed(event_id, success=False, error_message=err_msg)
            return

        # 4. Execute Full Pipeline
        from src.core.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline()
        email_meta = {
            "sender": event.email_metadata.sender,
            "subject": email_subject,
            "body": event.email_metadata.body_snippet or "",
            "event_id": event_id,
            "message_id": message_id,
        }
        result = pipeline.run_pipeline(
            file_path=temp_path,
            mime_type=event.mime_type,
            email_metadata=email_meta,
        )

        orders = result.orders
        final_code = result.supplier_code
        supplier_name = result.supplier_name
        pending_new_items = result.pending_new_items

        try:
            gmail_service = get_gmail_service()
        except Exception as gmail_err:
            logger.error(f"{ctx}Failed to initialize Gmail service: {gmail_err}", exc_info=True)
            gmail_service = None
        if not gmail_service:
            logger.warning(f"{ctx}Gmail service not available. Feedback emails will not be sent.")

        if not orders:
            logger.warning(f"{ctx}No orders extracted from {event.filename}")
            failed_order_id = save_failed_order_to_firestore(
                event_id=event_id,
                source_file_uri=event.gcs_uri,
                filename=event.filename,
                sender=event.email_metadata.sender,
                subject=email_subject,
                message_id=event.email_metadata.message_id,
                thread_id=event.email_metadata.thread_id,
                error="No orders extracted",
                stage="EXTRACTION",
                supplier_code=final_code,
                supplier_name=supplier_name,
                is_test=is_test_sender(event.email_metadata.sender),
                feedback_email_status=EMAIL_STATUS_PENDING,
                feedback_email_attempts=0,
                ingestion_source=INGESTION_SOURCE_EMAIL,
                sender_email=sender_email,
            )
            feedback_email_status, feedback_email_attempts, outbox_id = _queue_and_attempt_response_email(
                event_id=event_id,
                email_type="FAILURE",
                event=event,
                body=get_text("email_fail_body"),
                is_html=False,
                gmail_service=gmail_service,
                failed_order_id=failed_order_id,
            )

            _track_event_status(
                event_id,
                status="FAILED",
                stage="EXTRACTION",
                details=_event_details(
                    event,
                    error="No orders extracted",
                    supplier_code=final_code,
                    supplier_name=supplier_name,
                    feedback_email_status=feedback_email_status,
                    feedback_email_attempts=feedback_email_attempts,
                    extra={
                        key: value
                        for key, value in {
                            "failed_order_id": failed_order_id,
                            "response_email_outbox_id": outbox_id,
                        }.items()
                        if value
                    },
                ),
            )
            processing_lock.mark_message_completed(event_id, success=False, error_message="No orders extracted")
            return

        logger.info(f"{ctx}✅ Successfully extracted {len(orders)} order(s).")
        original_attachment_name = os.path.basename((event.filename or "").strip()) or "original_document"
        attachment_refs = [
            {
                "type": "gcs_source",
                "gcs_uri": event.gcs_uri,
                "filename": original_attachment_name,
            }
        ]
        order_ids: list[str] = []
        is_test_order = is_test_sender(event.email_metadata.sender)
        if is_test_order:
            logger.info(f"{ctx}Marking extracted orders as test (sender={event.email_metadata.sender})")

        # Build Message Body (HTML with RTL support)
        msg_body = f"""
            <div dir="rtl" style="font-family: Arial, sans-serif; text-align: right; line-height: 1.5;">
                <p>{get_text("email_greeting")}</p>
                <p>{get_text("email_processed_intro", subject=email_subject)}</p>
            """

        for i, order in enumerate(orders):
            logger.info(
                f"{ctx}--- Processing Order {i + 1}/{len(orders)}: Invoice {order.invoice_number or 'Unknown'} ---"
            )
            order.is_test = is_test_order

            new_items_count = len(result.new_items_data) if i == 0 else 0

            doc_id = save_order_to_firestore(
                order,
                event.gcs_uri,
                is_test=is_test_order,
                metadata={
                    "ingestion_source": INGESTION_SOURCE_EMAIL,
                    "subject": email_subject,
                    "sender": event.email_metadata.sender,
                    "sender_email": sender_email,
                    "filename": event.filename,
                    "phase1_reasoning": result.phase1_reasoning,
                },
                new_items_data=result.new_items_data if i == 0 else None,
                added_items_barcodes=result.added_barcodes if i == 0 and not pending_new_items else None,
            )
            if not doc_id:
                raise RuntimeError(f"Failed to persist order {order.invoice_number or i + 1} to Firestore")
            logger.info(f"{ctx}✅ Order saved to Firestore (ID: {doc_id}).")
            order_ids.append(doc_id)

            if i == 0 and pending_new_items:
                try:
                    added_count = ItemsService().add_new_items_batch(pending_new_items)
                    logger.info(f"{ctx}✅ Persisted {added_count} staged new items to DB.")
                except Exception as item_err:
                    logger.error(f"{ctx}Failed to persist staged new items: {item_err}")

            safe_invoice_num = re.sub(r"[^a-zA-Z0-9_-]", "_", str(order.invoice_number))
            safe_supplier_code = re.sub(r"[^a-zA-Z0-9_-]", "_", str(final_code))
            order_excel_filename = f"order_{safe_invoice_num}_{safe_supplier_code}.xlsx"
            attachment_refs.append(
                {
                    "type": "order_excel",
                    "order_id": doc_id,
                    "filename": order_excel_filename,
                }
            )
            if new_items_count > 0:
                new_items_filename = f"new_items_{safe_invoice_num}_{safe_supplier_code}.xlsx"
                attachment_refs.append(
                    {
                        "type": "new_items_excel",
                        "order_id": doc_id,
                        "supplier_code": final_code,
                        "filename": new_items_filename,
                    }
                )

            msg_body += f"<hr><h3>{get_text('metric_invoice')}: {order.invoice_number or 'Unknown'}</h3>"
            msg_body += "<ul>"
            msg_body += f"<li>{get_text('email_att_extracted', count=len(order.line_items)).strip()}</li>"
            msg_body += f"<li>{get_text('email_att_supplier', name=supplier_name, code=final_code).strip()}</li>"
            msg_body += f"<li>{get_text('email_est_cost', cost=order.processing_cost_ils).strip()}</li>"

            if new_items_count > 0:
                msg_body += f"<li>{get_text('email_att_new_items', count=new_items_count).strip()}</li>"

            if final_code == "UNKNOWN":
                msg_body += f"<li><span style='color: orange;'>{get_text('email_warn_unknown').strip()}</span></li>"

            if order.warnings:
                for warn in order.warnings:
                    msg_body += f"<li><span style='color: orange;'>{warn.strip()}</span></li>"

            msg_body += "</ul>"

            if order.notes or order.math_reasoning or order.qty_reasoning:
                msg_body += (
                    "<div style='background-color: #f9f9f9; padding: 10px; border-radius: 5px; margin: 10px 0;'>"
                )
                if order.notes:
                    msg_body += f"<strong>{get_text('ai_notes_title')}</strong><br>{order.notes}<br>"
                if order.math_reasoning:
                    msg_body += (
                        f"<p><strong>{get_text('ai_reasoning_title')} (מתמטי):</strong><br>{order.math_reasoning}</p>"
                    )
                if order.qty_reasoning:
                    msg_body += (
                        f"<p><strong>{get_text('ai_reasoning_title')} (כמותי):</strong><br>{order.qty_reasoning}</p>"
                    )
                msg_body += "</div>"

            # Note: The Cloud Function is assumed to be in Prod
            # However `get_web_ui_url` now behaves smartly
            edit_url = f"{settings.get_web_ui_url}/?order_id={doc_id}"
            msg_body += f"<p>✏️ {get_text('email_edit_link').strip()}<br>"
            msg_body += f"<a href='{edit_url}'>{edit_url}</a></p>"

        msg_body += f"<br><p>{get_text('email_signoff')}</p>"
        msg_body += "</div>"

        logger.info(f"{ctx}>>> QUEUING RESPONSE EMAIL to {event.email_metadata.sender}...")
        response_email_status, response_email_attempts, outbox_id = _queue_and_attempt_response_email(
            event_id=event_id,
            email_type="SUCCESS",
            event=event,
            body=msg_body,
            is_html=True,
            gmail_service=gmail_service,
            attachment_refs=attachment_refs,
            order_ids=order_ids,
        )
        if response_email_status == EMAIL_STATUS_SENT:
            logger.info(f"{ctx}✅ Pipeline complete. Email sent.")
        elif response_email_status == EMAIL_STATUS_FAILED_PERMANENT:
            logger.error(f"{ctx}Pipeline complete, but response email failed permanently.")
        else:
            logger.warning(f"{ctx}Pipeline complete. Email queued for retry ({response_email_status}).")

        _track_event_status(
            event_id,
            status="COMPLETED",
            stage="FINISHED",
            details=_event_details(
                event,
                supplier_code=final_code,
                supplier_name=supplier_name,
                extra={
                    "orders_count": len(orders),
                    "order_ids": order_ids,
                    "is_test": is_test_order,
                    "response_email_status": response_email_status,
                    "response_email_attempts": response_email_attempts,
                    "response_email_outbox_id": outbox_id,
                },
            ),
        )
        processing_lock.mark_message_completed(event_id, success=True)

    except Exception as e:
        logger.error(f"{_ctx(event_id, message_id)}Fatal error in process_order_event: {e}", exc_info=True)
        if event:
            _track_event_status(event_id, status="FAILED", stage="FATAL", details=_event_details(event, error=str(e)))
        else:
            _track_event_status(event_id, status="FAILED", stage="FATAL", details={"error": str(e)})
        if processing_lock:
            processing_lock.mark_message_completed(event_id, success=False, error_message=str(e))
        if event:
            if not gmail_service:
                try:
                    gmail_service = get_gmail_service()
                except Exception as gmail_err:
                    logger.error(
                        f"{_ctx(event_id, message_id)}Failed to initialize Gmail service for error reply: {gmail_err}"
                    )
                    gmail_service = None
            _queue_and_attempt_response_email(
                event_id=event_id,
                email_type="FAILURE",
                event=event,
                body=get_text("email_err_body_prefix") + str(e),
                is_html=False,
                gmail_service=gmail_service,
            )
        raise
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
