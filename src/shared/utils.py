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
