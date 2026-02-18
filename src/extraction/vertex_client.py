import io
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import List, Optional, Tuple

import openpyxl
import pandas as pd
from google import genai
from google.genai import errors, types
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.extraction.prompts import get_invoice_extraction_prompt, get_supplier_detection_prompt
from src.extraction.schemas import pdf_response_schema, single_order_schema

# Emails to exclude from supplier detection context
from src.shared.config import settings
from src.shared.constants import MAX_RETRIES, VALIDATION_TOLERANCE, VAT_RATE
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder, MultiOrderResponse

logger = get_logger(__name__)

# Emails to exclude from supplier detection context
EXCLUDED_EMAILS = settings.excluded_emails

# Path to supplier database
SUPPLIERS_EXCEL_PATH = os.path.join(os.path.dirname(__file__), "../../data-excel/suppliers.xlsx")

# Global client variable
_client = None


def read_excel_safe(file_path: str) -> pd.DataFrame:
    """
    Robust Excel reader that handles files with invalid XML/styles
    by falling back to openpyxl in read-only/data-only mode.
    """
    try:
        # Try standard pandas read (fastest, preserves logic)
        return pd.read_excel(file_path)
    except Exception as e:
        logger.warning(f"Standard pd.read_excel failed: {e}. Attempting fallback with openpyxl...")
        try:
            # Fallback: Read using openpyxl directly in read-only mode (ignores styles)
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            try:
                ws = wb.active
                data = ws.values
                # Get columns from first row
                columns = next(data)
                # Create DataFrame from remaining rows
                df = pd.DataFrame(data, columns=columns)
                logger.info("Fallback Excel read successful.")
                return df
            finally:
                wb.close()
        except Exception as fallback_e:
            logger.error(f"Fallback Excel read (openpyxl) failed: {fallback_e}")

            logger.info("Attempting Level 3 Fallback: Raw XML Parsing...")
            try:
                # Level 3: Raw XML parsing (bypassing openpyxl entirely)
                return read_xlsx_via_xml(file_path)
            except Exception as xml_e:
                logger.error(f"Level 3 XML read failed: {xml_e}")
                # Raise the ORIGINAL error (usually the most descriptive) or the last one
                raise e from xml_e


def read_xlsx_via_xml(file_path: str) -> pd.DataFrame:
    """
    Parses an XLSX file by directly reading the XML components,
    bypassing openpyxl's validation/stylesheet loading.

    This is used when the file has corrupted styles/XML that openpyxl can't handle.
    """
    with zipfile.ZipFile(file_path, "r") as z:
        # 1. Load Shared Strings (if exists)
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                tree = ET.parse(f)
                root = tree.getroot()
                # Namespace usually: {http://schemas.openxmlformats.org/spreadsheetml/2006/main}
                # But using local name is safer
                for si in root.findall(".//{*}si"):
                    # Text can be in <t> directly or in <r><t> (rich text)
                    text_nodes = si.findall(".//{*}t")
                    text = "".join(node.text or "" for node in text_nodes)
                    shared_strings.append(text)

        # 2. Load Worksheet (assume sheet1 for now, or find first available)
        sheet_path = None
        # Try finding regular worksheet list
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_path = name
                break

        if not sheet_path:
            raise ValueError("No worksheet found in XLSX archive")

        logger.info(f"Parsing raw XML from {sheet_path}...")

        data_rows = []
        with z.open(sheet_path) as f:
            # Iterative parsing to save memory
            context = ET.iterparse(f, events=("end",))

            current_row = []

            for _event, elem in context:
                if elem.tag.endswith("row"):
                    # Finish row
                    data_rows.append(current_row)
                    current_row = []
                    elem.clear()  # Free memory
                elif elem.tag.endswith("c"):
                    # Cell
                    cell_type = elem.get("t")
                    cell_value = None

                    # Find value node <v>
                    v_node = elem.find(".//{*}v")
                    if v_node is not None and v_node.text:
                        val = v_node.text
                        if cell_type == "s":  # Shared String
                            try:
                                idx = int(val)
                                cell_value = shared_strings[idx] if idx < len(shared_strings) else val
                            except Exception:
                                cell_value = val
                        elif cell_type == "b":  # Boolean
                            cell_value = val == "1"
                        else:
                            # Try number
                            try:
                                cell_value = float(val) if "." in val else int(val)
                            except Exception:
                                cell_value = val

                    # Direct inline string <is><t>...
                    if cell_value is None and cell_type == "inlineStr":
                        t_node = elem.find(".//{*}is/{*}t")
                        if t_node is not None:
                            cell_value = t_node.text

                    # Note: XML doesn't strictly guarantee column order if empty cells are skipped.
                    # For simplicity in this fallback, we just append.
                    # Providing full grid support requires parsing 'r' attribute (e.g. A1, B1).
                    current_row.append(cell_value)

    if not data_rows:
        return pd.DataFrame()

    # Calculate max columns across ALL rows to ensure no data is lost
    max_cols = max(len(r) for r in data_rows)

    # Pad all rows to max_cols to ensure consistent DataFrame structure
    normalized_data = []
    for row in data_rows:
        padding = [None] * (max_cols - len(row))
        normalized_data.append(row + padding)

    logger.info(f"Level 3 XML extraction successful. Max columns: {max_cols}")

    # Create DataFrame using the first row as the header to match pd.read_excel default behavior
    # But generate names for the extra columns
    header_row = normalized_data[0]
    data_body = normalized_data[1:]

    # Handle duplicate columns in header if any (pandas does this automatically usually, but we are manual here)
    # We'll just pass the data and headers to DataFrame constructor
    # However, if header_row has None values for the extra columns, we should give them names
    columns = []
    for i, col in enumerate(header_row):
        if col is None:
            columns.append(f"Unnamed: {i}")
        else:
            columns.append(str(col))

    return pd.DataFrame(data_body, columns=columns)


def init_client(project_id: str = None, location: str = None, api_key: str = None):
    """
    Initialize the Gen AI Client.
    Priority:
    1. Arguments passed directly
    2. Settings (Environment Variables)
    """
    global _client

    # Fallback to settings
    project_id = project_id or settings.PROJECT_ID
    location = location or settings.LOCATION or "global"

    if not api_key and settings.GEMINI_API_KEY:
        api_key = settings.GEMINI_API_KEY.get_secret_value()

    # Priority: Vertex AI (Project) > API Key (Studio)
    if project_id:
        logger.info(f"Initializing Gen AI Client with VERTEX AI (Project: {project_id})...")
        _client = genai.Client(vertexai=True, project=project_id, location=location)
    elif api_key:
        logger.info("Initializing Gen AI Client with API KEY (AI Studio mode)...")
        _client = genai.Client(api_key=api_key)
    else:
        logger.error("Error: Must provide either project_id OR api_key.")


def is_retryable_error(exception):
    """
    Retry on 5xx Server Errors OR 429 Resource Exhausted (Quota) errors.
    """
    if isinstance(exception, errors.ServerError):
        return True
    if isinstance(exception, errors.ClientError):
        # Check for 429 in various attributes or string representation
        # It's safer to be broad here for 429 specifically
        code = getattr(exception, "code", None) or getattr(exception, "status_code", None)
        if code == 429:
            return True
        if "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception):
            return True
    return False


@retry(
    retry=retry_if_exception(is_retryable_error),
    stop=stop_after_attempt(8),  # Increased to 8 attempts for 429 handling
    wait=wait_exponential(multiplier=2, min=4, max=120),  # Increased max wait to 120s for backoff
    before_sleep=before_sleep_log(logging.getLogger(), logging.WARNING),
)
def generate_content_safe(model, contents, config):
    """
    Wrapper for generate_content with robust retries for 503 Service Unavailable errors.
    """
    global _client
    if not _client:
        raise ValueError("Client not initialized")

    return _client.models.generate_content(model=model, contents=contents, config=config)


def filter_email_context(email_text: str) -> str:
    """
    Filter out excluded emails from the email body text.
    This prevents the LLM from incorrectly identifying internal emails as suppliers.

    Args:
        email_text: Raw email body text

    Returns:
        Filtered email text with excluded emails removed
    """
    if not email_text:
        return ""

    filtered_text = email_text
    for excluded_email in EXCLUDED_EMAILS:
        # Case-insensitive replacement
        pattern = re.compile(re.escape(excluded_email), re.IGNORECASE)
        filtered_text = pattern.sub("[FILTERED]", filtered_text)

    return filtered_text


def load_suppliers_csv() -> str:
    """
    DEPRECATED: Use SupplierService.get_suppliers_csv() instead.

    Load supplier database from Excel and convert to CSV text for LLM context.
    This function is kept for backward compatibility but should not be used.

    Returns:
        CSV string containing supplier data (code, name, phone, email, global_id)
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
    email_body: str, invoice_file_path: str = None, invoice_mime_type: str = None, suppliers_csv: str = None
) -> tuple[str, float]:
    """
    Phase 1 LLM Call: Detect supplier code from email context, invoice, and supplier database.

    Args:
        email_body: The email body text (will be filtered for excluded emails)
        invoice_file_path: Optional path to the invoice file (PDF or Excel)
        invoice_mime_type: MIME type of the invoice file
        suppliers_csv: Optional pre-loaded supplier CSV. If None, loads from SupplierService.

    Returns:
        Tuple of (supplier_code, confidence_score)
        supplier_code is "UNKNOWN" if no match found
    """
    global _client
    if not _client:
        logger.error("Client not initialized. Call init_client() first.")
        return ("UNKNOWN", 0.0)

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
            # Fallback to Excel
            suppliers_csv = load_suppliers_csv()

    if not suppliers_csv:
        logger.warning("Warning: No supplier data available for matching")
        return ("UNKNOWN", 0.0)

    # Build content parts for the LLM
    content_parts = []

    # Add invoice file if provided
    invoice_context = ""
    if invoice_file_path and os.path.exists(invoice_file_path):
        logger.info(f"Including invoice file in Phase 1: {invoice_file_path}")

        # Handle different file types
        if invoice_mime_type and "pdf" in invoice_mime_type.lower():
            # PDF file - upload as bytes
            try:
                with open(invoice_file_path, "rb") as f:
                    file_data = f.read()
                content_parts.append(types.Part.from_bytes(data=file_data, mime_type="application/pdf"))
                invoice_context = "[Invoice PDF attached above]"
            except Exception as e:
                logger.warning(f"Warning: Could not attach PDF: {e}")

        elif invoice_mime_type and ("excel" in invoice_mime_type.lower() or "spreadsheet" in invoice_mime_type.lower()):
            # Excel file - convert to CSV text
            try:
                df = read_excel_safe(invoice_file_path)
                excel_csv = df.to_csv(index=False)
                invoice_context = f"INVOICE DATA (Excel converted to CSV):\n{excel_csv}"
            except Exception as e:
                logger.warning(f"Warning: Could not read Excel for Phase 1: {e}")

        else:
            # Unknown type - try to read as text or Excel
            try:
                df = pd.read_excel(invoice_file_path)
                excel_csv = df.to_csv(index=False)
                invoice_context = f"INVOICE DATA (Excel converted to CSV):\n{excel_csv}"
            except Exception:
                logger.warning(f"Warning: Unknown file type for Phase 1: {invoice_mime_type}")

    prompt = get_supplier_detection_prompt(filtered_email, invoice_context, suppliers_csv)

    # Add text prompt
    content_parts.append(types.Part.from_text(text=prompt))

    model_name = "gemini-2.5-flash"
    logger.warning(f">>> Phase 1: Starting Supplier Detection using {model_name}...")
    logger.debug(f"Phase 1 Context: Email Snippet={filtered_email[:100]}..., Invoice Context={invoice_context[:100]}...")

    try:
        response = generate_content_safe(
            model=model_name,
            contents=[types.Content(role="user", parts=content_parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "supplier_code": {"type": "STRING"},
                        "confidence": {"type": "NUMBER"},
                        "reasoning": {"type": "STRING"},
                    },
                    "required": ["supplier_code", "confidence", "reasoning"],
                },
                temperature=0.0,
            ),
        )

        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw_json)

        supplier_code = result.get("supplier_code", "UNKNOWN")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")

        logger.warning(f"Phase 1 Finished: Model={model_name}, Supplier={supplier_code}, Confidence={confidence:.2f}")
        logger.info(f"Phase 1 Reasoning: {reasoning}")

        return (supplier_code, confidence)

    except Exception as e:
        logger.error(f"Error in supplier detection: {e}")
        return ("UNKNOWN", 0.0)


def extract_invoice_data(
    file_path: str,
    mime_type: str = None,
    email_context: str = None,
    supplier_instructions: str = None,
    retry_count: int = 0,
) -> list[ExtractedOrder]:
    """
    Phase 2 LLM Call: Extract invoice details from document.
    Supports PDF and Excel files.

    This function ONLY handles the interaction with the LLM (Prompting + Parsing).
    Validation and post-processing are now handled by OrderProcessor.

    Args:
        file_path: Path to the invoice file
        mime_type: Optional mime type override
        email_context: Optional text from the email body
        supplier_instructions: Optional supplier-specific instructions
        retry_count: Current retry attempt (used to toggle prompt versions)

    Returns:
        List of ExtractedOrder objects found in the document.
    """
    global _client
    if not _client:
        logger.error("Client not initialized. Call init_client() first.")
        return []

    # Use v2 (raw extraction) for first attempt, v1 (LLM-calculated) for retries
    prompt_version = "v2" if retry_count == 0 else "v1"
    prompt_text = get_invoice_extraction_prompt(
        email_context=email_context,
        supplier_instructions=supplier_instructions,
        version=prompt_version,
        enable_code_execution=(retry_count > 0),
    )

    # Use a more powerful model for retries
    model_name = "gemini-2.5-pro" if retry_count > 0 else "gemini-2.5-flash"
    
    logger.warning(f">>> Phase 2: Starting Extraction (Attempt {retry_count}) using {model_name}...")
    logger.info(f"File: {os.path.basename(file_path)} | Prompt Version: {prompt_version}")

    # Auto-detect MIME type if not provided
    if mime_type is None:
        ext = os.path.splitext(file_path.lower())[1]
        mime_types = {
            ".pdf": "application/pdf",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
        }
        mime_type = mime_types.get(ext, "application/pdf")

    try:
        with open(file_path, "rb") as f:
            file_content = f.read()
    except FileNotFoundError:
        logger.error(f"Error: File not found at {file_path}")
        return []

    # Handle Excel files by converting to text (CSV)
    excel_mime_types = ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"]
    file_part = None

    if mime_type in excel_mime_types:
        try:
            df = read_excel_safe(file_path)
            # Convert to CSV string - huge context saving vs raw binary
            csv_text = df.to_csv(index=False)
            file_part = types.Part.from_text(text=csv_text)
        except Exception as e:
            logger.error(f"Error converting Excel file: {e}")
            return []
    else:
        # Default: Send as raw bytes (PDF, Image)
        file_part = types.Part.from_bytes(data=file_content, mime_type=mime_type)

    # RETRY CONFIG: Enable Code Execution for retries
    current_tools = None
    current_schema = None

    if retry_count > 0:
        current_tools = [types.Tool(code_execution=types.ToolCodeExecution())]
        current_schema = None
    else:
        current_tools = None
        current_schema = pdf_response_schema

    try:
        response = generate_content_safe(
            model=model_name,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        file_part,
                        types.Part.from_text(text=prompt_text),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json" if current_schema else "text/plain",
                response_schema=current_schema,
                tools=current_tools,
                temperature=0.0,
            ),
        )

        # Robustly extract text from response parts (handles code execution warning)
        if response.candidates and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if part.text is not None]
            raw_json = "".join(text_parts)
        else:
            raw_json = ""

        # If using Code Execution (retry), extract JSON from markdown block
        if retry_count > 0:
            if "```json" in raw_json:
                try:
                    raw_json = raw_json.split("```json")[1].split("```")[0].strip()
                except IndexError:
                    pass
            else:
                raw_json = raw_json.replace("```json", "").replace("```", "").strip()

        # Clean formatting
        raw_json = raw_json.replace("```json", "").replace("```", "").strip()

        # New logic to make it one line for logs
        json_one_line = ""
        try:
            parsed = json.loads(raw_json)
            json_one_line = json.dumps(parsed, ensure_ascii=False)
        except Exception:
            json_one_line = raw_json.replace("\n", " ").replace("\r", "")

        # Log for cloud logging
        logger.info(f"✅ Phase 2 Finished (Model={model_name}). JSON received.")
        
        try:
            parsed_json = json.loads(raw_json)
            # Log as structured data for advanced filtering
            # Note: with StructuredLogHandler, extra fields are added to jsonPayload
            logger.info("AI Model Response (Phase 2 - Structured)", extra={
                "json_payload": parsed_json,
                "event_type": "ai_response",
                "attempt": retry_count,
                "model": model_name
            })
        except json.JSONDecodeError:
            logger.error(f"❌ AI returned invalid JSON: {raw_json[:200]}...")

        multi_order = MultiOrderResponse.model_validate_json(raw_json)
        return multi_order.orders

    except Exception as e:
        logger.error(f"Gemini API or Parsing failed: {e}")
        raise e
