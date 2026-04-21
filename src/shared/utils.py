import os
from email.utils import parseaddr

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

# Standard MIME type mappings for supported files
SUPPORTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".txt": "text/plain",
}

# MIME types that we treat as "Excel" and should be converted to CSV
EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def get_mime_type(file_path: str) -> str:
    """
    Detects the MIME type of a file based on its extension.
    Defaults to application/pdf if unknown (historical project behavior).
    """
    ext = os.path.splitext(file_path.lower())[1]
    return SUPPORTED_MIME_TYPES.get(ext, "application/pdf")


def is_excel_file(mime_type: str) -> bool:
    """
    Checks if a MIME type is a recognized Excel format.
    """
    return mime_type in EXCEL_MIME_TYPES


def convert_pdf_bytes_to_images(pdf_bytes: bytes, dpi: int = 200) -> list[bytes]:
    """
    Converts a raw PDF byte stream into a list of PNG images (one per page)
    using PyMuPDF (fitz).

    Args:
        pdf_bytes (bytes): The raw bytes of the PDF file.
        dpi (int): The resolution for rendering (default 200 for good OCR).

    Returns:
        list[bytes]: A list of bytes objects, each representing a Rendered PNG image.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Run: pip install pymupdf")
        return []

    images = []
    try:
        # Open the PDF from memory
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # Render page to a pixmap using specified DPI
            pix = page.get_pixmap(dpi=dpi)
            # Convert pixmap to PNG bytes
            img_bytes = pix.tobytes("png")
            images.append(img_bytes)
        doc.close()
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}")

    return images


def extract_sender_email(sender: str | None) -> str:
    """
    Extract a normalized email address from a sender string.
    Handles formats like 'Name <user@example.com>' and plain addresses.
    """
    if not sender:
        return ""
    _, parsed_email = parseaddr(sender)
    email = (parsed_email or sender).strip().lower()
    return email if "@" in email else ""


def is_test_sender(sender: str | None) -> bool:
    """
    Returns True when sender belongs to configured test sender emails.
    """
    sender_email = extract_sender_email(sender)
    return bool(sender_email and sender_email in settings.test_order_emails)


def is_allowed_sender(sender: str | None) -> bool:
    """
    Returns True when sender matches configured allowed emails.
    Supports exact email entries and domain entries like "@example.com".
    Empty allowlists permit all senders.
    """
    allowed_emails = settings.allowed_emails
    if not allowed_emails:
        return True

    sender_email = extract_sender_email(sender)
    if not sender_email:
        return False

    return any(
        sender_email == allowed_entry or (allowed_entry.startswith("@") and sender_email.endswith(allowed_entry))
        for allowed_entry in allowed_emails
    )
