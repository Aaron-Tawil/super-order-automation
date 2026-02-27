import os

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
        import logging
        logging.getLogger(__name__).error("PyMuPDF (fitz) is not installed. Run: pip install pymupdf")
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
        import logging
        logging.getLogger(__name__).error(f"Error converting PDF to images: {e}")
        
    return images
