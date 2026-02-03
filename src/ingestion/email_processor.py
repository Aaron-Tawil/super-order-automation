import os
import base64
import pickle
import mimetypes
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

from src.extraction.vertex_client import init_client, process_invoice, detect_supplier
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import generate_new_items_excel, filter_new_items_from_order
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService, UNKNOWN_SUPPLIER
from src.ingestion.gcs_writer import upload_to_gcs
from src.shared.session_store import create_session
from src.shared.translations import get_text

# Load env vars
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
WEB_UI_URL = os.getenv("WEB_UI_URL", "http://localhost:8501")


def get_gmail_service():
    """
    Load authorized credentials for Gmail API.
    
    Supports two modes:
    1. Cloud: Load from GMAIL_TOKEN environment variable (base64-encoded pickle from Secret Manager)
    2. Local: Load from token.pickle file
    """
    import base64
    creds = None
    
    # Try loading from Secret Manager (Cloud Functions environment)
    token_from_secret = os.getenv('GMAIL_TOKEN')
    if token_from_secret:
        try:
            # Secret Manager stores as base64-encoded pickle bytes
            token_bytes = base64.b64decode(token_from_secret)
            creds = pickle.loads(token_bytes)
            logging.info("Loaded credentials from Secret Manager")
        except Exception as e:
            logging.error(f"Failed to load token from secret: {e}")
    
    # Fallback to local file
    if not creds and os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
            logging.info("Loaded credentials from token.pickle")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logging.info("Refreshed expired credentials")
        else:
            logging.error("[!] Credentials not valid or missing.")
            return None
            
    return build('gmail', 'v1', credentials=creds)

def send_reply(service, original_thread_id, original_message_id_header, to, subject, body, attachment_paths: Optional[List[str]] = None):
    """
    Reply to the sender with one or more attachments.
    Uses proper Thread ID and Message-ID headers to ensure threading consistency.
    """
    import time
    
    message = MIMEMultipart()
    message['to'] = to
    message['subject'] = get_text("email_subject_re", subject=subject)
    
    # Use RFC822 Message-ID if available for threading headers
    if original_message_id_header:
        message['In-Reply-To'] = original_message_id_header
        message['References'] = original_message_id_header
    else:
        # Fallback to internal ID (less reliable for some clients)
        message['In-Reply-To'] = original_thread_id
        message['References'] = original_thread_id
    
    message.attach(MIMEText(body, 'plain'))
    
    # Handle multiple attachments
    if attachment_paths:
        for attachment_path in attachment_paths:
            if attachment_path and os.path.exists(attachment_path):
                content_type, encoding = mimetypes.guess_type(attachment_path)
                if content_type is None or encoding is not None:
                    content_type = 'application/octet-stream'
                main_type, sub_type = content_type.split('/', 1)
                
                with open(attachment_path, 'rb') as fp:
                    msg = MIMEBase(main_type, sub_type)
                    msg.set_payload(fp.read())
                
                encoders.encode_base64(msg)
                msg.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_path))
                message.attach(msg)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    
    # Retry logic for transient network/SSL errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            service.users().messages().send(userId='me', body={'raw': raw_message, 'threadId': original_thread_id}).execute()
            logging.info(f"Reply sent to {to} in thread {original_thread_id}")
            return  # Success!
        except Exception as e:
            error_str = str(e)
            
            # Check for 404 (Thread not found) - don't retry
            if "404" in error_str or "Requested entity was not found" in error_str:
                logging.warning(f"Could not send reply: Original thread {original_thread_id} not found (404). Details: {e}")
                return
            
            # Check for SSL/network errors - retry with backoff
            if any(keyword in error_str for keyword in ["SSL", "EOF", "Connection", "Timeout"]):
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logging.warning(f"Network/SSL error on attempt {attempt + 1}/{max_retries}: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            # Other errors or final retry failed
            logging.error(f"An error occurred sending reply: {e}")
            return

def get_email_body(payload: dict) -> str:
    """Recursively extract plain text body from email payload."""
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                if 'data' in part['body']:
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif 'parts' in part: # Nested multipart
                body += get_email_body(part)
    elif payload.get('mimeType') == 'text/plain':
         if 'data' in payload['body']:
            return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    return body

def process_single_attachment(service, thread_id, msg_id_header, sender, subject, email_body_text, attachment_data, attachment_filename, attachment_mime_type):
    logging.info(f"Processing attachment: {attachment_filename} ({attachment_mime_type})")
    
    # Save to temp
    # Use /tmp for Cloud Functions writable directory
    temp_path = f"/tmp/temp_{attachment_filename}" if os.name != 'nt' else f"temp_{attachment_filename}"
    excel_filename = None
    new_items_excel = None

    try:
        with open(temp_path, "wb") as f:
            f.write(attachment_data)
        
        # === PRE-EXTRACTION UPLOAD ===
        # Upload original file to GCS early, before heavy AI processing.
        # This avoids SSL/timeout issues that can happen when the network is stressed during AI extraction.
        source_file_uri = None
        try:
            source_file_uri = upload_to_gcs(temp_path, attachment_filename)
        except Exception as gcs_err:
            logging.warning(f"Failed to upload to GCS (early attempt): {gcs_err}")

        # Initialize AI Client
        init_client(api_key=API_KEY)
        
        # === PHASE 1: SUPPLIER DETECTION ===
        logging.info("Phase 1: Detecting supplier from email + invoice context...")
        supplier_service = SupplierService()
        
        # Pass both email body AND invoice file to detection
        detected_supplier_code, detection_confidence = detect_supplier(
            email_body=email_body_text,
            invoice_file_path=temp_path,
            invoice_mime_type=attachment_mime_type
        )
        
        # Validate detected supplier exists in our database
        if detected_supplier_code != "UNKNOWN":
            supplier_data = supplier_service.get_supplier(detected_supplier_code)
            if not supplier_data:
                logging.warning(f"LLM detected supplier code {detected_supplier_code} not found in database, falling back to UNKNOWN")
                detected_supplier_code = "UNKNOWN"
        
        # Get supplier-specific instructions if available
        supplier_instructions = None
        if detected_supplier_code != "UNKNOWN":
            supplier_instructions = supplier_service.get_supplier_instructions(detected_supplier_code)
            if supplier_instructions:
                logging.info(f"Found special instructions for supplier {detected_supplier_code}")
        
        # === PHASE 2: PRODUCT EXTRACTION ===
        logging.info("Phase 2: Extracting products from invoice...")
        order = process_invoice(
            temp_path, 
            mime_type=attachment_mime_type, 
            email_context=email_body_text,
            supplier_instructions=supplier_instructions
        )
        
        if order:
            logging.info("Extraction Successful!")

            # === SUPPLIER MATCHING (Fallback if Phase 1 was uncertain) ===
            # If Phase 1 detected UNKNOWN or low confidence, try matching from extracted data
            if detected_supplier_code == "UNKNOWN" or detection_confidence < 0.7:
                logging.info("Phase 1 uncertain, attempting fallback matching from extracted data...")
                fallback_code = supplier_service.match_supplier(
                    global_id=order.supplier_global_id,
                    email=order.supplier_email,
                    phone=order.supplier_phone
                )
                if fallback_code != "UNKNOWN":
                    detected_supplier_code = fallback_code
                    logging.info(f"Fallback matching succeeded: {detected_supplier_code}")
            
            supplier_code = detected_supplier_code
            supplier_unknown = supplier_service.is_unknown(supplier_code)
            
            # Get supplier name from supplier_service
            supplier_data = supplier_service.get_supplier(supplier_code) if not supplier_unknown else None
            supplier_name = supplier_data.get('name', 'Unknown Supplier') if supplier_data else 'Unknown Supplier'
            
            if supplier_unknown:
                logging.warning(f"Could not match supplier for order (code: {supplier_code})")
            else:
                logging.info(f"Final supplier: {supplier_name} -> {supplier_code}")

            # Populate supplier details in order object for dashboard
            order.supplier_name = supplier_name
            order.supplier_code = supplier_code

            # === NEW ITEMS DETECTION ===
            new_items_count = 0
            invalid_barcode_count = 0
            
            try:
                # Initialize services
                items_service = ItemsService()
                
                # Get all barcodes from order
                all_barcodes = [
                    str(item.barcode).strip() 
                    for item in order.line_items 
                    if item.barcode
                ]
                
                # Filter for valid barcodes (>= 11 digits)
                valid_barcodes = [b for b in all_barcodes if len(b) >= 11]
                invalid_barcode_count = len(all_barcodes) - len(valid_barcodes)
                
                if invalid_barcode_count > 0:
                    logging.info(f"Filtered out {invalid_barcode_count} invalid barcodes (<11 digits).")
                
                # Check which VALID barcodes are new
                new_barcodes = items_service.get_new_barcodes(valid_barcodes)
                logging.info(f"Found {len(new_barcodes)} new barcodes out of {len(valid_barcodes)} valid ones")
                
                if new_barcodes:
                    # Filter to get new items line data
                    new_items = filter_new_items_from_order(order, new_barcodes)
                    new_items_count = len(new_items)
                    
                    if new_items:
                        # Generate new items Excel
                        safe_invoice_num = "".join([c if c.isalnum() or c in ('-','_') else '_' for c in str(order.invoice_number)])
                        new_items_excel = f"/tmp/new_items_{safe_invoice_num}.xlsx" if os.name != 'nt' else f"new_items_{safe_invoice_num}.xlsx"
                        generate_new_items_excel(new_items, supplier_code, new_items_excel)
                        
                        # Add new items to database
                        items_to_add = [
                            {"barcode": item.barcode, "name": item.description}
                            for item in new_items
                        ]
                        added = items_service.add_new_items_batch(items_to_add)
                        logging.info(f"Added {added} new items to database")
                        
                        # Track added items for Revert functionality
                        added_barcodes = [item.barcode for item in new_items]
                
            except Exception as new_items_err:
                logging.error(f"Error in new items detection: {new_items_err}", exc_info=True)
                # Continue with normal processing even if new items detection fails
            
            # Generate main Excel
            safe_invoice_num = "".join([c if c.isalnum() or c in ('-','_') else '_' for c in str(order.invoice_number)])
            excel_filename = f"/tmp/extracted_{safe_invoice_num}.xlsx" if os.name != 'nt' else f"extracted_{safe_invoice_num}.xlsx"
            generate_excel_from_order(order, excel_filename)
            
            # Build reply body
            body_lines = [
                get_text("email_greeting"),
                f"",
                get_text("email_processed_intro", subject=subject),
                f"",
                get_text("email_attachments"),
                get_text("email_att_original", filename=attachment_filename),
                get_text("email_att_extracted", count=len(order.line_items)),
                get_text("email_att_supplier", name=supplier_name, code=supplier_code),
            ]
            
            if new_items_count > 0:
                body_lines.append(get_text("email_att_new_items", count=new_items_count))
            
            # Check for extraction failures
            extraction_warnings = []
            
            if extraction_warnings:
                body_lines.append(f"")
                body_lines.append(get_text("email_warn_phase2", fields=', '.join(extraction_warnings)))
            
            if supplier_unknown:
                body_lines.append(f"")
                body_lines.append(get_text("email_warn_unknown"))
            
            if invalid_barcode_count > 0:
                 body_lines.append(f"")
                 body_lines.append(get_text("email_warn_barcodes", count=invalid_barcode_count))
            
            # Check for MISSING barcodes in the final output (items that were kept but have no barcode)
            missing_barcode_count = sum(1 for item in order.line_items if not item.barcode or not str(item.barcode).strip())
            if missing_barcode_count > 0:
                body_lines.append(f"")
                body_lines.append(get_text("email_warn_no_barcode", count=missing_barcode_count))
            
            # Add Validation Warnings if any
            if hasattr(order, 'warnings') and order.warnings:
                body_lines.append(f"")
                for w in order.warnings:
                    body_lines.append(f"⚠️ {w}")
            
            # Try to create session for web UI editing
            edit_link = None
            try:
                # Prepare new_items data for dashboard display
                new_items_data = []
                if 'new_items' in locals() and new_items:
                    new_items_data = [
                        {
                            'barcode': str(item.barcode) if item.barcode else '',
                            'description': item.description,
                            'final_net_price': item.final_net_price or 0
                        }
                        for item in new_items
                    ]
                
                # Prepare metadata
                session_metadata = {
                    "subject": subject,
                    "sender": sender,
                    "filename": attachment_filename,
                    "source_file_uri": source_file_uri,
                    "added_items_barcodes": added_barcodes if 'added_barcodes' in locals() else [],
                    "new_items": new_items_data  # For dashboard new items section
                }
                
                session_id = create_session(order, session_metadata)
                edit_link = f"{WEB_UI_URL}?session={session_id}"
                logging.info(f"Created session: {session_id}")
            except Exception as session_err:
                logging.warning(f"Could not create session (expected in Cloud Functions): {session_err}")

            if edit_link:
                body_lines.append(f"")
                body_lines.append(get_text("email_edit_link"))
                body_lines.append(edit_link)
            
            body_lines.append(f"")
            body_lines.append(get_text("email_signoff"))
            body = "\n".join(body_lines)
            
            # Collect attachments (include original document)
            attachments = [temp_path, excel_filename]  # Original file first
            if new_items_excel:
                attachments.append(new_items_excel)
            
            send_reply(service, thread_id, msg_id_header, sender, subject, body, attachments)
            return True
        else:
            logging.warning("Extraction returned None.")
            send_reply(service, thread_id, msg_id_header, sender, subject, get_text("email_fail_body"), None)
            return False
    except Exception as inner_e:
        logging.error(f"Extraction error: {inner_e}", exc_info=True)
        send_reply(service, thread_id, msg_id_header, sender, subject, f"{get_text('email_err_body_prefix')}{inner_e}", None)
        return False
    finally:
        # Cleanup
        if os.path.exists(temp_path): os.remove(temp_path)
        if excel_filename and os.path.exists(excel_filename): os.remove(excel_filename)
        if new_items_excel and os.path.exists(new_items_excel): os.remove(new_items_excel)

def process_unread_emails():
    """
    Scans for unread emails with attachments and processes them.
    Returns: Number of emails processed.
    """
    service = get_gmail_service()
    if not service:
        logging.error("Failed to get Gmail service.")
        return 0

    try:
        # Search for UNREAD emails with ATTACHMENTS
        results = service.users().messages().list(
            userId='me', 
            labelIds=['INBOX'], 
            q='is:unread has:attachment', 
            maxResults=5
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            logging.info("No unread messages with attachments found.")
            return 0

        logging.info(f"Found {len(messages)} unread messages.")
        
        processed_count = 0
        for msg_item in messages:
            msg_id = msg_item['id']
            # Fetch full details
            msg = service.users().messages().get(userId='me', id=msg_id).execute()
            
            # Check if it's still unread (double check)
            if 'UNREAD' not in msg['labelIds']:
                logging.info(f"Message {msg_id} already read. Skipping.")
                continue

            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            thread_id = msg['threadId']
            msg_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
            
            # Safety Filter: Replies
            if subject.lower().startswith("re:"):
                logging.info(f"Skipping Reply/Thread: {subject}")
                continue

            # Get my profile email
            profile = service.users().getProfile(userId='me').execute()
            my_email = profile['emailAddress']

            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            
            logging.info(f"Processing Email: {subject} from {sender}")
            
            # Ignore self
            if my_email.lower() in sender.lower():
                logging.info(f"Skipping email from myself ({sender})")
                continue

            # Mark as READ IMMEDIATELY
            logging.info(f"Marking message {msg_id} as READ.")
            service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()

            # Extract Email Body
            email_body_text = get_email_body(msg['payload'])
            logging.info(f"Extracted email body length: {len(email_body_text)} chars")

            # Find PDF or Excel attachments
            parts = msg['payload'].get('parts', [])
            found_attachments = []
            
            # Supported file types
            SUPPORTED_EXTENSIONS = {
                '.pdf': 'application/pdf',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            }
            
            for part in parts:
                filename = part.get('filename', '')
                if filename:
                    ext = os.path.splitext(filename.lower())[1]
                    if ext in SUPPORTED_EXTENSIONS:
                        if 'data' in part['body']:
                            file_data = base64.urlsafe_b64decode(part['body']['data'])
                        else:
                            att_id = part['body']['attachmentId']
                            att = service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
                            file_data = base64.urlsafe_b64decode(att['data'])
                        
                        found_attachments.append({
                            'data': file_data,
                            'filename': filename,
                            'mime_type': SUPPORTED_EXTENSIONS[ext]
                        })
            
            if found_attachments:
                logging.info(f"Found {len(found_attachments)} attachments.")
                for att in found_attachments:
                    process_single_attachment(service, thread_id, msg_id_header, sender, subject, email_body_text, att['data'], att['filename'], att['mime_type'])
                processed_count += 1
            else:
                logging.info("No supported attachment found (PDF or Excel).")
        
        return processed_count

    except Exception as e:
        logging.error(f"Error processing messages: {e}", exc_info=True)
        return 0
