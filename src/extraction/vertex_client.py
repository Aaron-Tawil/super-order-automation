"""
Backward-compatible facade for extraction client functions.

New code should prefer importing from `src.extraction.vertex.*` modules directly.
This wrapper keeps legacy imports stable while the implementation is split by concern.
"""

from google import genai

from src.extraction.vertex import (
    InvoiceExtractionResult,
    SupplierDetectionResult,
    filter_email_context,
    generate_content_safe,
    is_retryable_error,
    load_suppliers_csv,
    read_excel_safe,
    read_xlsx_via_xml,
)
from src.extraction.vertex import (
    detect_supplier as _detect_supplier_impl,
)
from src.extraction.vertex import (
    extract_invoice_data as _extract_invoice_data_impl,
)
from src.extraction.vertex.client import _client as _shared_client
from src.extraction.vertex.client import init_client as _init_client_impl
from src.extraction.vertex.metadata import extract_response_metadata as _extract_response_metadata
from src.shared.config import settings

# Kept for compatibility with older tests and debugging flows.
_client = _shared_client


def init_client(project_id: str = None, location: str = None, api_key: str = None):
    """
    Initialize the shared Gen AI client used by supplier detection and extraction phases.
    """
    global _client
    _client = _init_client_impl(
        project_id=project_id,
        location=location,
        api_key=api_key,
        settings_obj=settings,
        genai_module=genai,
    )
    return _client


def detect_supplier(
    email_body: str,
    invoice_file_path: str = None,
    invoice_mime_type: str = None,
    suppliers_csv: str = None,
) -> SupplierDetectionResult:
    """
    Legacy entry point for Phase 1 supplier detection.
    """
    return _detect_supplier_impl(
        email_body=email_body,
        invoice_file_path=invoice_file_path,
        invoice_mime_type=invoice_mime_type,
        suppliers_csv=suppliers_csv,
    )


def extract_invoice_data(
    file_path: str,
    mime_type: str = None,
    email_context: str = None,
    supplier_instructions: str = None,
    retry_count: int = 0,
) -> InvoiceExtractionResult:
    """
    Legacy entry point for Phase 2 invoice extraction.
    """
    return _extract_invoice_data_impl(
        file_path=file_path,
        mime_type=mime_type,
        email_context=email_context,
        supplier_instructions=supplier_instructions,
        retry_count=retry_count,
    )


__all__ = [
    "init_client",
    "detect_supplier",
    "extract_invoice_data",
    "read_excel_safe",
    "read_xlsx_via_xml",
    "_extract_response_metadata",
    "is_retryable_error",
    "generate_content_safe",
    "filter_email_context",
    "load_suppliers_csv",
    "SupplierDetectionResult",
    "InvoiceExtractionResult",
    "settings",
    "genai",
    "_client",
]
