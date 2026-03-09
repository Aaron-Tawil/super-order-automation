import base64
import json
import os
import re
import uuid
from typing import Any

import functions_framework
from pydantic import ValidationError

from src.core.events import OrderIngestedEvent
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import generate_new_items_excel
from src.extraction.vertex_client import init_client
from src.ingestion.firestore_writer import save_order_to_firestore, upsert_processing_event
from src.ingestion.gcs_writer import download_file_from_gcs
from src.ingestion.gmail_utils import get_gmail_service, send_reply
from src.shared.config import settings
from src.shared.idempotency_service import IdempotencyService
from src.shared.logger import get_logger
from src.shared.translations import get_text
from src.shared.utils import is_test_sender

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
    attachments = []
    attachment_names: dict[str, str] = {}
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
        ctx = _ctx(event_id, message_id)
        _track_event_status(
            event_id,
            status="PROCESSING",
            stage="RECEIVED",
            details={"filename": event.filename, "gcs_uri": event.gcs_uri},
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
            _track_event_status(event_id, status="FAILED", stage="DOWNLOAD", details={"error": err_msg})
            processing_lock.mark_message_completed(event_id, success=False, error_message=err_msg)
            return

        # 4. Execute Full Pipeline
        from src.core.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline()
        email_meta = {
            "sender": event.email_metadata.sender,
            "subject": event.email_metadata.subject,
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

        gmail_service = get_gmail_service()
        if not gmail_service:
            logger.warning(f"{ctx}Gmail service not available. Feedback emails will not be sent.")

        if not orders:
            logger.warning(f"{ctx}No orders extracted from {event.filename}")
            _track_event_status(
                event_id,
                status="FAILED",
                stage="EXTRACTION",
                details={"error": "No orders extracted", "supplier_code": final_code},
            )
            processing_lock.mark_message_completed(event_id, success=False, error_message="No orders extracted")
            if gmail_service:
                send_reply(
                    gmail_service,
                    event.email_metadata.thread_id,
                    event.email_metadata.message_id,
                    event.email_metadata.sender,
                    event.email_metadata.subject,
                    get_text("email_fail_body"),
                )
            return

        logger.info(f"{ctx}✅ Successfully extracted {len(orders)} order(s).")
        attachments = [temp_path]
        original_attachment_name = os.path.basename((event.filename or "").strip()) or "original_document"
        attachment_names[temp_path] = original_attachment_name
        is_test_order = is_test_sender(event.email_metadata.sender)
        if is_test_order:
            logger.info(f"{ctx}Marking extracted orders as test (sender={event.email_metadata.sender})")

        # Build Message Body (HTML with RTL support)
        msg_body = f"""
            <div dir="rtl" style="font-family: Arial, sans-serif; text-align: right; line-height: 1.5;">
                <p>{get_text("email_greeting")}</p>
                <p>{get_text("email_processed_intro", subject=event.email_metadata.subject)}</p>
            """

        for i, order in enumerate(orders):
            logger.info(
                f"{ctx}--- Processing Order {i + 1}/{len(orders)}: "
                f"Invoice {order.invoice_number or 'Unknown'} ---"
            )
            order.is_test = is_test_order

            new_items_count = len(result.new_items_data) if i == 0 else 0

            if new_items_count > 0:
                logger.info(f"{ctx}🆕 Found {new_items_count} NEW items in this batch. Generating attachment.")
                safe_invoice_num = re.sub(r"[^a-zA-Z0-9_-]", "_", str(order.invoice_number))
                safe_supplier_code = re.sub(r"[^a-zA-Z0-9_-]", "_", str(final_code))

                from src.shared.models import LineItem

                fake_new_items = [LineItem(**item) for item in result.new_items_data]
                new_items_filename = f"new_items_{safe_invoice_num}_{safe_supplier_code}.xlsx"
                new_items_path = f"/tmp/{new_items_filename}"
                generate_new_items_excel(fake_new_items, final_code, new_items_path)
                attachments.append(new_items_path)

            doc_id = save_order_to_firestore(
                order,
                event.gcs_uri,
                is_test=is_test_order,
                metadata={
                    "subject": event.email_metadata.subject,
                    "sender": event.email_metadata.sender,
                    "filename": event.filename,
                    "phase1_reasoning": result.phase1_reasoning,
                },
                new_items_data=result.new_items_data if i == 0 else None,
            )
            logger.info(f"{ctx}✅ Order saved to Firestore (ID: {doc_id}).")

            safe_invoice_num = re.sub(r"[^a-zA-Z0-9_-]", "_", str(order.invoice_number))
            safe_supplier_code = re.sub(r"[^a-zA-Z0-9_-]", "_", str(final_code))
            order_excel_filename = f"order_{safe_invoice_num}_{safe_supplier_code}.xlsx"
            order_excel_path = f"/tmp/{order_excel_filename}"
            try:
                generate_excel_from_order(order, order_excel_path)
                attachments.append(order_excel_path)
            except Exception as excel_err:
                logger.error(f"{ctx}Failed to generate Order Excel: {excel_err}")

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
                    "<div style='background-color: #f9f9f9; padding: 10px; "
                    "border-radius: 5px; margin: 10px 0;'>"
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

        if gmail_service:
            logger.info(f"{ctx}>>> SENDING FEEDBACK EMAIL to {event.email_metadata.sender}...")
            send_reply(
                gmail_service,
                event.email_metadata.thread_id,
                event.email_metadata.message_id,
                event.email_metadata.sender,
                event.email_metadata.subject,
                msg_body,
                attachment_paths=attachments,
                attachment_names=attachment_names,
                is_html=True,
            )
            logger.info(f"{ctx}✅ Pipeline complete. Email sent.")

        _track_event_status(
            event_id,
            status="COMPLETED",
            stage="FINISHED",
            details={
                "orders_count": len(orders),
                "supplier_code": final_code,
                "filename": event.filename,
                "is_test": is_test_order,
            },
        )
        processing_lock.mark_message_completed(event_id, success=True)

    except Exception as e:
        logger.error(f"{_ctx(event_id, message_id)}Fatal error in process_order_event: {e}", exc_info=True)
        _track_event_status(event_id, status="FAILED", stage="FATAL", details={"error": str(e)})
        if processing_lock:
            processing_lock.mark_message_completed(event_id, success=False, error_message=str(e))
        if event:
            if not gmail_service:
                gmail_service = get_gmail_service()
            if gmail_service:
                send_reply(
                    gmail_service,
                    event.email_metadata.thread_id,
                    event.email_metadata.message_id,
                    event.email_metadata.sender,
                    event.email_metadata.subject,
                    get_text("email_err_body_prefix") + str(e),
                )
        raise
    finally:
        for path in attachments[1:]:
            if path and os.path.exists(path):
                os.remove(path)
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
