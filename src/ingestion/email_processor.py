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
# Load env vars
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
# Auto-detect GCP Project (Cloud Run sets GOOGLE_CLOUD_PROJECT automatically)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
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

        # Initialize AI Client (Prioritize Vertex AI)
        init_client(api_key=API_KEY, project_id=PROJECT_ID)
        
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
        orders = process_invoice(
            temp_path, 
            mime_type=attachment_mime_type, 
            email_context=email_body_text,
            supplier_instructions=supplier_instructions
        )
        
        if orders:
            logging.info(f"Extraction Successful! Found {len(orders)} orders.")
            
            all_attachments = [temp_path] # Original file first
            all_body_parts = [
                get_text("email_greeting"),
                f"",
                get_text("email_processed_intro", subject=subject),
                f""
            ]

            # Initialize items service once
            items_service = ItemsService()
            
            for i, order in enumerate(orders):
                logging.info(f"Processing Order {i+1}/{len(orders)} (Invoice: {order.invoice_number})")
                
                # === SUPPLIER MATCHING (Fallback if Phase 1 was uncertain) ===
                current_supplier_code = detected_supplier_code
                if current_supplier_code == "UNKNOWN" or detection_confidence < 0.7:
                    logging.info(f"Fallback matching for order {i+1}...")
                    fallback_code = supplier_service.match_supplier(
                        global_id=order.supplier_global_id,
                        email=order.supplier_email,
                        phone=order.supplier_phone
                    )
                    if fallback_code != "UNKNOWN":
                        current_supplier_code = fallback_code
                
                supplier_unknown = supplier_service.is_unknown(current_supplier_code)
                supplier_data = supplier_service.get_supplier(current_supplier_code) if not supplier_unknown else None
                supplier_name = supplier_data.get('name', 'Unknown Supplier') if supplier_data else 'Unknown Supplier'
                
                order.supplier_name = supplier_name
                order.supplier_code = current_supplier_code

                # === NEW ITEMS DETECTION ===
                new_items_count = 0
                invalid_barcode_count = 0
                added_barcodes = []
                new_items_excel = None
                
                try:
                    all_barcodes = [str(item.barcode).strip() for item in order.line_items if item.barcode]
                    valid_barcodes = [b for b in all_barcodes if len(b) >= 11]
                    invalid_barcode_count = len(all_barcodes) - len(valid_barcodes)
                    
                    new_barcodes = items_service.get_new_barcodes(valid_barcodes)
                    if new_barcodes:
                        new_items = filter_new_items_from_order(order, new_barcodes)
                        new_items_count = len(new_items)
                        if new_items:
                            safe_inv = "".join([c if c.isalnum() or c in ('-','_') else '_' for c in str(order.invoice_number or f"order_{i+1}")])
                            new_items_excel = f"/tmp/new_items_{safe_inv}.xlsx" if os.name != 'nt' else f"new_items_{safe_inv}.xlsx"
                            generate_new_items_excel(new_items, current_supplier_code, new_items_excel)
                            all_attachments.append(new_items_excel)
                            
                            items_to_add = [{"barcode": item.barcode, "name": item.description} for item in new_items]
                            items_service.add_new_items_batch(items_to_add)
                            added_barcodes = [item.barcode for item in new_items]
                except Exception as e:
                    logging.error(f"Error in new items detection for order {i+1}: {e}")

                # Generate main Excel
                safe_inv = "".join([c if c.isalnum() or c in ('-','_') else '_' for c in str(order.invoice_number or f"order_{i+1}")])
                excel_filename = f"/tmp/extracted_{safe_inv}.xlsx" if os.name != 'nt' else f"extracted_{safe_inv}.xlsx"
                generate_excel_from_order(order, excel_filename)
                all_attachments.append(excel_filename)
                
                # Build order summary for email
                order_summary = [
                    f"--- {get_text('order')} {i+1} : {order.invoice_number or 'N/A'} ---",
                    get_text("email_att_extracted", count=len(order.line_items)),
                    get_text("email_att_supplier", name=supplier_name, code=current_supplier_code),
                ]
                
                if new_items_count > 0:
                    order_summary.append(get_text("email_att_new_items", count=new_items_count))
                
                if supplier_unknown:
                    order_summary.append(f"⚠️ {get_text('email_warn_unknown')}")
                
                if invalid_barcode_count > 0:
                     order_summary.append(f"⚠️ {get_text('email_warn_barcodes', count=invalid_barcode_count)}")
                
                missing_barcode_count = sum(1 for item in order.line_items if not item.barcode or not str(item.barcode).strip())
                if missing_barcode_count > 0:
                    order_summary.append(f"⚠️ {get_text('email_warn_no_barcode', count=missing_barcode_count)}")
                
                if hasattr(order, 'warnings') and order.warnings:
                    for w in order.warnings:
                        order_summary.append(f"⚠️ {w}")
                
                # Create session for dashboard
                try:
                    new_items_data = []
                    if 'new_items' in locals() and new_items:
                        new_items_data = [{'barcode': str(item.barcode), 'description': item.description, 'final_net_price': item.final_net_price or 0} for item in new_items]
                    
                    session_metadata = {
                        "subject": subject,
                        "sender": sender,
                        "filename": attachment_filename,
                        "source_file_uri": source_file_uri,
                        "added_items_barcodes": added_barcodes,
                        "new_items": new_items_data
                    }
                    session_id = create_session(order, session_metadata)
                    edit_link = f"{WEB_UI_URL}?session={session_id}"
                    order_summary.append(f"{get_text('email_edit_link')}: {edit_link}")
                except Exception as e:
                    logging.warning(f"Could not create session for order {i+1}: {e}")

                all_body_parts.extend(order_summary)
                all_body_parts.append("") # Spacer between orders

            all_body_parts.append(get_text("email_signoff"))
            body = "\n".join(all_body_parts)
            
            send_reply(service, thread_id, msg_id_header, sender, subject, body, all_attachments)
            return True
        else:
            logging.warning("Extraction returned no orders.")
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
        
        # Initialize Idempotency Service
        from src.shared.idempotency_service import IdempotencyService
        idempotency = IdempotencyService()

        for msg_item in messages:
            msg_id = msg_item['id']
            
            # === IDEMPOTENCY CHECK ===
            # Try to acquire lock for this message ID
            if not idempotency.check_and_lock_message(msg_id):
                logging.info(f"Skipping message {msg_id}: Already processed or locked.")
                continue
                
            try:
                # Fetch full details
                msg = service.users().messages().get(userId='me', id=msg_id).execute()
            except Exception as msg_err:
                logging.error(f"Failed to fetch message details for {msg_id}: {msg_err}")
                continue

            
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
                all_success = True
                for att in found_attachments:
                    success = process_single_attachment(service, thread_id, msg_id_header, sender, subject, email_body_text, att['data'], att['filename'], att['mime_type'])
                    if not success:
                        all_success = False
                
                processed_count += 1
                idempotency.mark_message_completed(msg_id, success=all_success)
            else:
                logging.info("No supported attachment found (PDF or Excel).")
                # Still mark as completed so we don't keep checking it
                idempotency.mark_message_completed(msg_id, success=True)
            
            # except Exception is caught in the outer block, but we need to mark failed there too?
            # The outer try/except (line 523) breaks the whole loop. 
            # We should probably wrap the inner message processing to be safe.

        return processed_count

    except Exception as e:
        logging.error(f"Error processing messages: {e}", exc_info=True)
        return 0

