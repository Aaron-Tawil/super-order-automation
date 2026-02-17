import base64
import json
import os
from typing import Any, Dict

import functions_framework
from pydantic import ValidationError

from src.core.events import OrderIngestedEvent
from src.core.processor import OrderProcessor
from src.extraction.vertex_client import detect_supplier, init_client
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import filter_new_items_from_order, generate_new_items_excel
from src.ingestion.firestore_writer import save_order_to_firestore
from src.ingestion.gcs_writer import download_file_from_gcs
from src.ingestion.gmail_utils import get_gmail_service, send_reply
from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.session_store import create_session
from src.shared.translations import get_text

logger = get_logger(__name__)

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
            return

        logger.info(f"========================================================================")
        logger.info(f">>> STARTING ORDER PIPELINE: {event.event_id} (File: {event.filename})")
        logger.info(f"========================================================================")

        # 3. Download File
        temp_path = f"/tmp/{event.filename}" if os.name != "nt" else f"temp_{event.filename}"
        if not download_file_from_gcs(event.gcs_uri, temp_path):
            logger.error(f"Failed to download file from {event.gcs_uri}")
            return

        try:
            # 4. Phase 1: Supplier Detection
            logger.info(">>> PHASE 1: Supplier Detection...")
            email_context = event.email_metadata.body_snippet
            
            detected_code, confidence = detect_supplier(
                email_body=email_context,
                invoice_file_path=temp_path,
                invoice_mime_type=event.mime_type
            )
            
            supplier_service = SupplierService()
            supplier_instructions = None
            supplier_name = "Unknown"
            
            if detected_code != "UNKNOWN":
                s_data = supplier_service.get_supplier(detected_code)
                if s_data:
                    supplier_name = s_data.get("name", "Unknown")
                    supplier_instructions = s_data.get("special_instructions")
                    logger.info(f"✅ Supplier Identified: {supplier_name} ({detected_code}) with {confidence:.2f} confidence")
            else:
                logger.warning(f"⚠️ Supplier detection returned UNKNOWN for {event.filename}")
            
            # 5. Phase 2: Extraction
            logger.info(">>> PHASE 2: Extraction & Post-Processing...")
            processor = OrderProcessor()
            orders = processor.process_file(
                temp_path, 
                mime_type=event.mime_type, 
                email_context=email_context,
                supplier_instructions=supplier_instructions
            )

            gmail_service = get_gmail_service()
            if not gmail_service:
                logger.warning("Gmail Service NOT available. Feedback emails will not be sent.")

            if not orders:
                logger.warning(f"❌ No orders extracted from {event.filename}")
                if gmail_service:
                    send_reply(
                        gmail_service,
                        event.email_metadata.thread_id,
                        event.email_metadata.message_id,
                        event.email_metadata.sender,
                        event.email_metadata.subject,
                        get_text("email_fail_body")
                    )
                return

            logger.info(f"✅ Successfully extracted {len(orders)} order(s).")

            # 6. Finalize and Save to Firestore
            items_service = ItemsService()
            attachments = [temp_path]  # Start with original document
            
            # Build Message Body (HTML with RTL support)
            msg_body = f"""
            <div dir="rtl" style="font-family: Arial, sans-serif; text-align: right; line-height: 1.5;">
                <p>{get_text("email_greeting")}</p>
                <p>{get_text("email_processed_intro", subject=event.email_metadata.subject)}</p>
            """

            for i, order in enumerate(orders):
                logger.info(f"--- Processing Order {i+1}/{len(orders)}: Invoice {order.invoice_number or 'Unknown'} ---")
                
                # Fallback supplier matching
                final_code = detected_code
                if final_code == "UNKNOWN" or confidence < 0.7:
                    matched = supplier_service.match_supplier(
                        global_id=order.supplier_global_id,
                        email=order.supplier_email,
                        phone=order.supplier_phone
                    )
                    if matched != "UNKNOWN":
                        final_code = matched
                        s_data = supplier_service.get_supplier(final_code)
                        supplier_name = s_data.get("name", "Unknown") if s_data else "Unknown"
                        logger.info(f"✅ Supplier Fallback Match: {supplier_name} ({final_code})")

                # Enrich order object
                order.supplier_code = final_code
                order.supplier_name = supplier_name
                
                # 7. Identify and Handle New Items
                order_barcodes = [str(item.barcode).strip() for item in order.line_items if item.barcode]
                new_barcodes = items_service.get_new_barcodes(order_barcodes)
                new_items_count = 0
                
                if new_barcodes:
                    new_items = filter_new_items_from_order(order, new_barcodes)
                    new_items_count = len(new_items)
                    logger.info(f"🆕 Found {new_items_count} NEW items in this order.")
                    
                    items_to_add = [
                        {"barcode": item.barcode, "name": item.description} 
                        for item in new_items if item.barcode and len(str(item.barcode)) >= 11
                    ]
                    if items_to_add:
                        items_service.add_new_items_batch(items_to_add)
                        logger.info(f"✅ Auto-added {len(items_to_add)} valid new items to database.")
                    
                    safe_invoice_num = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in str(order.invoice_number)])
                    new_items_filename = f"new_items_{safe_invoice_num}_{final_code}.xlsx"
                    new_items_path = f"/tmp/{new_items_filename}"
                    generate_new_items_excel(new_items, final_code, new_items_path)
                    attachments.append(new_items_path)
                else:
                    logger.info("📦 No new items detected (all barcodes already in database).")

                # 8. Save to Firestore & Create Session
                doc_id = save_order_to_firestore(order, event.gcs_uri)
                session_id = create_session(order, metadata={
                    "subject": event.email_metadata.subject,
                    "sender": event.email_metadata.sender,
                    "filename": event.filename
                })
                logger.info(f"✅ Order saved to Firestore (ID: {doc_id}). Session created: {session_id}")
                
                # 9. Generate Order Excel Attachment
                safe_invoice_num = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in str(order.invoice_number)])
                order_excel_filename = f"order_{safe_invoice_num}_{final_code}.xlsx"
                order_excel_path = f"/tmp/{order_excel_filename}"
                try:
                    generate_excel_from_order(order, order_excel_path)
                    attachments.append(order_excel_path)
                except Exception as excel_err:
                    logger.error(f"Failed to generate Order Excel: {excel_err}")

                # 10. Add Order Section to Message Body (HTML)
                msg_body += f"<hr><h3>{get_text('metric_invoice')}: {order.invoice_number or 'Unknown'}</h3>"
                msg_body += "<ul>"
                msg_body += f"<li>{get_text('email_att_extracted', count=len(order.line_items)).strip()}</li>"
                msg_body += f"<li>{get_text('email_att_supplier', name=supplier_name, code=final_code).strip()}</li>"
                
                if new_items_count > 0:
                    msg_body += f"<li>{get_text('email_att_new_items', count=new_items_count).strip()}</li>"
                
                # Specific Warnings
                if final_code == "UNKNOWN":
                    msg_body += f"<li><span style='color: orange;'>{get_text('email_warn_unknown').strip()}</span></li>"
                
                if order.warnings:
                    for warn in order.warnings:
                        msg_body += f"<li><span style='color: orange;'>{warn.strip()}</span></li>"
                
                msg_body += "</ul>"
                
                # Edit Link with Session
                edit_url = f"{settings.WEB_UI_URL}/?session={session_id}"
                msg_body += f"<p>✏️ {get_text('email_edit_link').strip()}<br>"
                msg_body += f"<a href='{edit_url}'>{edit_url}</a></p>"

            # Finalize Message
            msg_body += f"<br><p>{get_text('email_signoff')}</p>"
            msg_body += "</div>"
            
            # Send Email
            if gmail_service:
                logger.info(f">>> SENDING FEEDBACK EMAIL to {event.email_metadata.sender}...")
                send_reply(
                    gmail_service,
                    event.email_metadata.thread_id,
                    event.email_metadata.message_id,
                    event.email_metadata.sender,
                    event.email_metadata.subject,
                    msg_body,
                    attachment_paths=attachments,
                    is_html=True
                )
                logger.info("✅ Pipeline complete. Email sent.")
            
            # Cleanup generated temp files (excluding the original document which is cleaned in finally)
            for path in attachments[1:]:  # skip original temp_path
                if path and os.path.exists(path):
                    os.remove(path)

        finally:
            # Cleanup original document
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        logger.error(f"Fatal error in process_order_event: {e}", exc_info=True)
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
                    get_text("email_err_body_prefix") + str(e)
                )
        raise e
