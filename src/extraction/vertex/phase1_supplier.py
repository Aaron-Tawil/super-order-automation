import json
import os
import re

import pandas as pd
from google.genai import types

from src.extraction.prompts import get_supplier_detection_prompt
from src.extraction.schemas import supplier_detection_schema
from src.shared.ai_cost import calculate_cost
from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.utils import get_mime_type, is_excel_file

from .client import generate_content_safe
from .excel_fallback import read_excel_safe
from .metadata import extract_response_metadata
from .types import SupplierDetectionResult

logger = get_logger(__name__)

SUPPLIERS_EXCEL_PATH = os.path.join(os.path.dirname(__file__), "../../../data-excel/suppliers.xlsx")


def filter_email_context(email_text: str) -> str:
    """
    Filter excluded emails from email context so internal addresses don't bias detection.
    Supports exact emails and wildcard domains prefixed with '@'.
    """
    if not email_text:
        return ""

    filtered_text = email_text
    for excluded_entry in settings.excluded_emails:
        excluded_entry = excluded_entry.strip()
        if not excluded_entry:
            continue

        if excluded_entry.startswith("@"):
            domain_pattern = re.escape(excluded_entry)
            full_pattern = r"\b[A-Za-z0-9._%+-]+" + domain_pattern + r"\b"
            pattern = re.compile(full_pattern, re.IGNORECASE)
            filtered_text = pattern.sub("[FILTERED_DOMAIN]", filtered_text)
        else:
            pattern = re.compile(re.escape(excluded_entry), re.IGNORECASE)
            filtered_text = pattern.sub("[FILTERED]", filtered_text)

    return filtered_text


def load_suppliers_csv() -> str:
    """
    Deprecated fallback: load suppliers from local Excel and return CSV text.
    Preferred source is SupplierService.get_suppliers_csv().
    """
    try:
        if not os.path.exists(SUPPLIERS_EXCEL_PATH):
            logger.warning(f"Warning: Suppliers Excel not found at {SUPPLIERS_EXCEL_PATH}")
            return ""

        df = pd.read_excel(SUPPLIERS_EXCEL_PATH)
        csv_text = df.to_csv(index=False)
        logger.info(f"Loaded {len(df)} suppliers from Excel for LLM context")
        return csv_text
    except Exception as e:
        logger.error(f"Error loading suppliers Excel: {e}")
        return ""


def detect_supplier(
    email_body: str,
    invoice_file_path: str = None,
    invoice_mime_type: str = None,
    suppliers_csv: str = None,
    trace_context: str = "",
) -> SupplierDetectionResult:
    """
    Phase 1 LLM call: detect supplier from email context, supplier list, and optional invoice.

    Returns:
        (supplier_code, confidence_score, phase1_cost, reasoning, result_dict, detected_email, detected_id)
    """
    # Filter excluded emails from context
    filtered_email = filter_email_context(email_body)

    # Load suppliers from SupplierService (Firestore) if not provided
    if suppliers_csv is None:
        try:
            from src.data.supplier_service import SupplierService

            supplier_service = SupplierService()
            suppliers_csv = supplier_service.get_suppliers_csv()
        except Exception as e:
            logger.warning(f"Warning: Could not load from SupplierService: {e}")
            suppliers_csv = load_suppliers_csv()

    if not suppliers_csv:
        logger.warning("Warning: No supplier data available for matching")
        return ("UNKNOWN", 0.0, 0.0, "", {}, None, None)

    content_parts = []
    invoice_context = ""

    if invoice_file_path and os.path.exists(invoice_file_path):
        logger.info(f"Including invoice file in Phase 1: {invoice_file_path}")

        if not invoice_mime_type:
            invoice_mime_type = get_mime_type(invoice_file_path)

        if is_excel_file(invoice_mime_type):
            try:
                df = read_excel_safe(invoice_file_path)
                excel_csv = df.to_csv(index=False)
                invoice_context = f"INVOICE DATA (Excel converted to CSV):\n{excel_csv}"
            except Exception as e:
                logger.warning(f"Warning: Could not read Excel for Phase 1: {e}")
        elif "pdf" in invoice_mime_type.lower():
            try:
                with open(invoice_file_path, "rb") as f:
                    file_data = f.read()
                content_parts.append(types.Part.from_bytes(data=file_data, mime_type="application/pdf"))
                invoice_context = "[Invoice PDF attached above]"
            except Exception as e:
                logger.warning(f"Warning: Could not attach PDF: {e}")
        else:
            logger.warning(
                f"Warning: Unknown or unsupported file type for Phase 1: {invoice_mime_type}. "
                "Attempting default PDF handling."
            )

    prompt = get_supplier_detection_prompt(filtered_email, invoice_context, suppliers_csv)
    content_parts.append(types.Part.from_text(text=prompt))

    model_name = "gemini-2.5-flash"
    logger.info(f"{trace_context}>>> Phase 1: Starting Supplier Detection using {model_name}...")
    logger.debug(
        f"{trace_context}Phase 1 Context: Email Snippet={filtered_email[:100]}..., "
        f"Invoice Context={invoice_context[:100]}..."
    )

    try:
        response = generate_content_safe(
            model=model_name,
            contents=[types.Content(role="user", parts=content_parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=supplier_detection_schema,
                temperature=0.0,
            ),
        )

        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw_json)

        supplier_code = result.get("supplier_code", "UNKNOWN")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")
        detected_email = result.get("detected_email")
        detected_id = result.get("detected_id")

        cost = 0.0
        try:
            response_metadata = extract_response_metadata(response)
            usage_metadata = response_metadata.get("usage", {})
            cost = calculate_cost(model_name, usage_metadata)
        except Exception as e:
            logger.warning(f"Failed to calculate cost/metadata for Phase 1: {e}")
            cost = 0.0

        summary = (
            f"{trace_context}Phase 1 Finished: Model={model_name}, Supplier={supplier_code}, "
            f"Email={detected_email}, ID={detected_id}, Confidence={confidence:.2f}, Cost=${cost:.6f}"
        )
        if supplier_code == "UNKNOWN":
            logger.warning(summary)
        else:
            logger.info(summary)
        logger.info(f"{trace_context}Phase 1 Reasoning: {reasoning}")

        logger.info(
            "AI Model Response (Phase 1 - Structured)",
            extra={
                "json_fields": {
                    "json_payload": result,
                    "event_type": "ai_response_phase1",
                    "model": model_name,
                }
            },
        )

        return (supplier_code, confidence, cost, reasoning, result, detected_email, detected_id)

    except Exception as e:
        logger.error(f"Error in supplier detection: {e}")
        return ("UNKNOWN", 0.0, 0.0, "", {}, None, None)
