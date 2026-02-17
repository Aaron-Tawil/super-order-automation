import base64
import mimetypes
import os
import pickle
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


def get_gmail_service():
    """
    Load authorized credentials for Gmail API.
    Supports Cloud (Secret Manager) and Local (token.pickle) modes.
    """
    creds = None

    # Try loading from Secret Manager
    token_from_secret = settings.GMAIL_TOKEN.get_secret_value() if settings.GMAIL_TOKEN else None
    if token_from_secret:
        try:
            token_bytes = base64.b64decode(token_from_secret)
            creds = pickle.loads(token_bytes)
            logger.info("Loaded credentials from Secret Manager")
        except Exception as e:
            logger.error(f"Failed to load token from secret: {e}")

    # Fallback to local file
    if not creds and os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
            logger.info("Loaded credentials from token.pickle")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logger.info("Refreshed expired credentials")
        else:
            logger.error("[!] Credentials not valid or missing.")
            return None

    return build("gmail", "v1", credentials=creds)


def send_reply(service, thread_id, msg_id_header, to, subject, body_text, attachment_paths=None, is_html=False):
    """
    Sends a reply to the original email thread.
    attachment_paths: List of file paths to attach.
    is_html: If True, sends as text/html, otherwise text/plain.
    """
    try:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
        message["In-Reply-To"] = msg_id_header
        message["References"] = msg_id_header

        subtype = "html" if is_html else "plain"
        msg = MIMEText(body_text, subtype)
        message.attach(msg)

        if attachment_paths:
            if isinstance(attachment_paths, str):
                attachment_paths = [attachment_paths]
                
            for attachment_path in attachment_paths:
                if attachment_path and os.path.exists(attachment_path):
                    content_type, encoding = mimetypes.guess_type(attachment_path)
                    if content_type is None or encoding is not None:
                        content_type = "application/octet-stream"
                    main_type, sub_type = content_type.split("/", 1)

                    with open(attachment_path, "rb") as f:
                        file_data = f.read()

                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(attachment_path)}",
                    )
                    message.attach(part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Retry logic for sending
        max_retries = 3
        for attempt in range(max_retries):
            try:
                service.users().messages().send(userId="me", body={"raw": raw_message, "threadId": thread_id}).execute()
                logger.info(f"Reply sent to {to} in thread {thread_id} with {len(attachment_paths) if attachment_paths else 0} attachments")
                return  # Success!
            except Exception as e:
                error_str = str(e)
                # Check for 404 (Thread not found) - don't retry
                if "404" in error_str or "Requested entity was not found" in error_str:
                    logger.warning(f"Could not send reply: Original thread {thread_id} not found (404). Details: {e}")
                    return

                # Check for SSL/network errors - retry with backoff
                if any(keyword in error_str for keyword in ["SSL", "EOF", "Connection", "Timeout"]):
                    if attempt < max_retries - 1:
                        wait_time = 2**attempt
                        logger.warning(
                            f"Network/SSL error on attempt {attempt + 1}/{max_retries}: {e}. Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue

                # Other errors or final retry failed
                logger.error(f"An error occurred sending reply: {e}")
                return

    except Exception as e:
        logger.error(f"Failed to build reply message: {e}")


def get_email_body(payload: dict) -> str:
    """Recursively extract plain text body from email payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                if "data" in part["body"]:
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
            elif "parts" in part:  # Nested multipart
                body += get_email_body(part)
    elif payload.get("mimeType") == "text/plain":
        if "data" in payload["body"]:
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
    return body
