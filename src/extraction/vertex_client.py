from google import genai
from google.genai import types
import os
import re
from typing import Optional, Tuple, List
import sys
import pandas as pd
import io
import json
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception, before_sleep_log
from google.genai import errors
from google.genai import errors
import openpyxl
import zipfile
import xml.etree.ElementTree as ET

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.models import ExtractedOrder, MultiOrderResponse
from src.shared.constants import VAT_RATE, VALIDATION_TOLERANCE, MAX_RETRIES

# Emails to exclude from supplier detection context
# Emails to exclude from supplier detection context
EXCLUDED_EMAILS = os.getenv("EXCLUDED_EMAILS", "").split(",") if os.getenv("EXCLUDED_EMAILS") else []

# Path to supplier database
SUPPLIERS_EXCEL_PATH = os.path.join(
    os.path.dirname(__file__), 
    '../../data-excel/suppliers.xlsx'
)

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
        print(f"Standard pd.read_excel failed: {e}. Attempting fallback with openpyxl...")
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
                print("Fallback Excel read successful.")
                return df
            finally:
                wb.close()
        except Exception as fallback_e:
            print(f"Fallback Excel read (openpyxl) failed: {fallback_e}")
            
            print("Attempting Level 3 Fallback: Raw XML Parsing...")
            try:
                # Level 3: Raw XML parsing (bypassing openpyxl entirely)
                return read_xlsx_via_xml(file_path)
            except Exception as xml_e:
                print(f"Level 3 XML read failed: {xml_e}")
                # Raise the ORIGINAL error (usually the most descriptive) or the last one
                raise e

def read_xlsx_via_xml(file_path: str) -> pd.DataFrame:
    """
    Parses an XLSX file by directly reading the XML components, 
    bypassing openpyxl's validation/stylesheet loading.
    
    This is used when the file has corrupted styles/XML that openpyxl can't handle.
    """
    with zipfile.ZipFile(file_path, 'r') as z:
        # 1. Load Shared Strings (if exists)
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            with z.open('xl/sharedStrings.xml') as f:
                tree = ET.parse(f)
                root = tree.getroot()
                # Namespace usually: {http://schemas.openxmlformats.org/spreadsheetml/2006/main}
                # But using local name is safer
                for si in root.findall('.//{*}si'):
                    # Text can be in <t> directly or in <r><t> (rich text)
                    text_nodes = si.findall('.//{*}t')
                    text = "".join(node.text or "" for node in text_nodes)
                    shared_strings.append(text)
        
        # 2. Load Worksheet (assume sheet1 for now, or find first available)
        sheet_path = None
        # Try finding regular worksheet list
        for name in z.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                sheet_path = name
                break
        
        if not sheet_path:
            raise ValueError("No worksheet found in XLSX archive")
            
        print(f"Parsing raw XML from {sheet_path}...")
        
        data_rows = []
        with z.open(sheet_path) as f:
            # Iterative parsing to save memory
            context = ET.iterparse(f, events=('end',))
            
            current_row = []
            
            for event, elem in context:
                if elem.tag.endswith('row'):
                    # Finish row
                    data_rows.append(current_row)
                    current_row = []
                    elem.clear() # Free memory
                elif elem.tag.endswith('c'):
                    # Cell
                    cell_type = elem.get('t')
                    cell_value = None
                    
                    # Find value node <v>
                    v_node = elem.find('.//{*}v')
                    if v_node is not None and v_node.text:
                        val = v_node.text
                        if cell_type == 's': # Shared String
                            try:
                                idx = int(val)
                                cell_value = shared_strings[idx] if idx < len(shared_strings) else val
                            except:
                                cell_value = val
                        elif cell_type == 'b': # Boolean
                            cell_value = (val == '1')
                        else:
                            # Try number
                            try:
                                cell_value = float(val) if '.' in val else int(val)
                            except:
                                cell_value = val
                    
                    # Direct inline string <is><t>...
                    if cell_value is None and cell_type == 'inlineStr':
                        t_node = elem.find('.//{*}is/{*}t')
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
        
    print(f"Level 3 XML extraction successful. Max columns: {max_cols}")
    
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


def init_client(project_id: str = None, location: str = "global", api_key: str = None):
    """
    Initialize the Gen AI Client.
    Priority:
    1. API Key (Google AI Studio) - Recommended for testing/MVP
    2. Vertex AI (GCP Project) - Recommended for Production
    """
    global _client
    
    # Priority: Vertex AI (Project) > API Key (Studio)
    if project_id:
        print(f"Initializing Gen AI Client with VERTEX AI (Project: {project_id})...")
        _client = genai.Client(
            vertexai=True, 
            project=project_id, 
            location=location
        )
    elif api_key:
        print("Initializing Gen AI Client with API KEY (AI Studio mode)...")
        _client = genai.Client(api_key=api_key)
    else:
        print("Error: Must provide either project_id OR api_key.")


def is_retryable_error(exception):
    """
    Retry on 5xx Server Errors OR 429 Resource Exhausted (Quota) errors.
    """
    if isinstance(exception, errors.ServerError):
        return True
    if isinstance(exception, errors.ClientError):
        # Check for 429 in various attributes or string representation
        # It's safer to be broad here for 429 specifically
        code = getattr(exception, 'code', None) or getattr(exception, 'status_code', None)
        if code == 429:
            return True
        if "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception):
            return True
    return False

@retry(
    retry=retry_if_exception(is_retryable_error),
    stop=stop_after_attempt(8),  # Increased to 8 attempts for 429 handling
    wait=wait_exponential(multiplier=2, min=4, max=120), # Increased max wait to 120s for backoff
    before_sleep=before_sleep_log(logging.getLogger(), logging.WARNING)
)
def generate_content_safe(model, contents, config):
    """
    Wrapper for generate_content with robust retries for 503 Service Unavailable errors.
    """
    global _client
    if not _client:
        raise ValueError("Client not initialized")
    
    return _client.models.generate_content(
        model=model,
        contents=contents,
        config=config
    )


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
            print(f"Warning: Suppliers Excel not found at {SUPPLIERS_EXCEL_PATH}")
            return ""
        
        df = pd.read_excel(SUPPLIERS_EXCEL_PATH)
        csv_text = df.to_csv(index=False)
        print(f"Loaded {len(df)} suppliers from Excel for LLM context")
        return csv_text
    except Exception as e:
        print(f"Error loading suppliers Excel: {e}")
        return ""


def detect_supplier(
    email_body: str, 
    invoice_file_path: str = None,
    invoice_mime_type: str = None,
    suppliers_csv: str = None
) -> Tuple[str, float]:
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
        print("Client not initialized. Call init_client() first.")
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
            print(f"Warning: Could not load from SupplierService: {e}")
            # Fallback to Excel
            suppliers_csv = load_suppliers_csv()
    
    if not suppliers_csv:
        print("Warning: No supplier data available for matching")
        return ("UNKNOWN", 0.0)
    
    # Build content parts for the LLM
    content_parts = []
    
    # Add invoice file if provided
    invoice_context = ""
    if invoice_file_path and os.path.exists(invoice_file_path):
        print(f"Including invoice file in Phase 1: {invoice_file_path}")
        
        # Handle different file types
        if invoice_mime_type and 'pdf' in invoice_mime_type.lower():
            # PDF file - upload as bytes
            try:
                with open(invoice_file_path, "rb") as f:
                    file_data = f.read()
                content_parts.append(
                    types.Part.from_bytes(data=file_data, mime_type="application/pdf")
                )
                invoice_context = "[Invoice PDF attached above]"
            except Exception as e:
                print(f"Warning: Could not attach PDF: {e}")
        
        elif invoice_mime_type and ('excel' in invoice_mime_type.lower() or 'spreadsheet' in invoice_mime_type.lower()):
            # Excel file - convert to CSV text
            try:
                df = read_excel_safe(invoice_file_path)
                excel_csv = df.to_csv(index=False)
                invoice_context = f"INVOICE DATA (Excel converted to CSV):\n{excel_csv}"
            except Exception as e:
                print(f"Warning: Could not read Excel for Phase 1: {e}")
        
        else:
            # Unknown type - try to read as text or Excel
            try:
                df = pd.read_excel(invoice_file_path)
                excel_csv = df.to_csv(index=False)
                invoice_context = f"INVOICE DATA (Excel converted to CSV):\n{excel_csv}"
            except:
                print(f"Warning: Unknown file type for Phase 1: {invoice_mime_type}")
    
    prompt = f"""
You are an expert at identifying suppliers from email communications and invoices.

TASK: Analyze the email body and invoice below, then match to a supplier from our database.

EMAIL BODY:
{filtered_email}

{invoice_context}

SUPPLIER DATABASE (CSV format):
{suppliers_csv}

INSTRUCTIONS:
1. Look for supplier identifiers in BOTH the email AND invoice:
- Business ID (עוסק/ח"פ) - usually a 9-digit number *Prioritize this.*
   - Company name (fuzzy match).
   - Phone number
   - Email address
   - Logo or letterhead text
2. Match these identifiers to the supplier database.
3. The supplier "קוד" (code) column is what you need to return.
4. Prioritize matches from the invoice over email if there's a conflict.
5. If you find a clear match, return the supplier code.
6. If you cannot find a confident match, return "UNKNOWN".

Output must strictly follow the defined schema.
"""
    
    # Add text prompt
    content_parts.append(types.Part.from_text(text=prompt))
    
    print("Phase 1: Detecting supplier from email + invoice context...")
    
    try:
        response = generate_content_safe(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=content_parts
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "supplier_code": {"type": "STRING"},
                        "confidence": {"type": "NUMBER"},
                        "reasoning": {"type": "STRING"}
                    },
                    "required": ["supplier_code", "confidence", "reasoning"]
                },
                temperature=0.0
            )
        )
        
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        

        result = json.loads(raw_json)
        
        supplier_code = result.get("supplier_code", "UNKNOWN")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")
        
        print(f"Phase 1 Result: Supplier={supplier_code}, Confidence={confidence:.2f}")
        print(f"Reasoning: {reasoning}")
        
        return (supplier_code, confidence)
        
    except Exception as e:
        print(f"Error in supplier detection: {e}")
        return ("UNKNOWN", 0.0)

def validate_order_totals(order: ExtractedOrder) -> Tuple[bool, float, float]:
    """
    Validates that the sum of line items matches the document total.
    
    Returns:
        Tuple[is_valid, calculated_total, difference]
    """
    if order.document_total_with_vat is None:
        # Cannot validate if no total is extracted
        return True, 0.0, 0.0

    calculated_net = sum(item.final_net_price * item.quantity for item in order.line_items)
    # Add VAT
    calculated_total_with_vat = calculated_net * (1 + VAT_RATE)
    
    diff = abs(calculated_total_with_vat - order.document_total_with_vat)
    
    is_valid = diff <= VALIDATION_TOLERANCE
    
    return is_valid, calculated_total_with_vat, diff

def validate_order_quantity(order: ExtractedOrder) -> Tuple[bool, float, float]:
    """
    Validates that the sum of line item quantities matches the document total quantity.
    
    Returns:
        Tuple[is_valid, calculated_total, difference]
    """
    if order.document_total_quantity is None:
        # Cannot validate if no total quantity is extracted
        return True, 0.0, 0.0

    calculated_quantity = sum((item.quantity or 0) for item in order.line_items)
    diff = abs(calculated_quantity - order.document_total_quantity)
    
    # Use a small tolerance for float comparison
    is_valid = diff <= 0.1
    
    return is_valid, calculated_quantity, diff

def process_invoice(file_path: str, mime_type: str = None, email_context: str = None, supplier_instructions: str = None, retry_count: int = 0) -> List[ExtractedOrder]:
    """
    Phase 2 LLM Call: Extract invoice details from document.
    Supports PDF and Excel files.
    Includes retry logic for validation failures.
    
    Args:
        file_path: Path to the invoice file
        mime_type: Optional mime type override
        email_context: Optional text from the email body to aid extraction (phone, address, etc)
        supplier_instructions: Optional supplier-specific extraction instructions from database
        retry_count: Internal counter for retries (max 1)
    
    Returns:
        List of ExtractedOrder objects found in the document.
    """
    global _client
    if not _client:
        print("Client not initialized. Call init_client() first.")
        return None

    print(f"Phase 2: Processing invoice: {file_path}")
    
    # Auto-detect MIME type if not provided
    if mime_type is None:
        ext = os.path.splitext(file_path.lower())[1]
        mime_types = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel'
        }
        mime_type = mime_types.get(ext, 'application/pdf')
        print(f"Auto-detected MIME type: {mime_type}")
    
    try:
        with open(file_path, "rb") as f:
            file_content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return []

    # Handle Excel files by converting to text (CSV)
    excel_mime_types = [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ]
    
    file_part = None
    
    if mime_type in excel_mime_types:
        print(f"Excel detected ({mime_type}). Converting to CSV text for Gemini...")
        try:
            df = read_excel_safe(file_path)
            # Convert to CSV string
            csv_text = df.to_csv(index=False)
            file_part = types.Part.from_text(text=csv_text)
            print("Successfully converted Excel to CSV text.")
        except Exception as e:
            print(f"Error converting Excel file: {e}")
            return []
    else:
        # Default: Send as raw bytes (PDF, Image)
        file_part = types.Part.from_bytes(data=file_content, mime_type=mime_type)

    prompt_text = ""
    if email_context:
        prompt_text += f"""
    CONTEXT FROM EMAIL BODY:
    {email_context}
    
    """

    prompt_text += """
    You are an expert data extraction assistant for an Accounting team.
    Extract the invoice details from this document into the required JSON format.
    
    IMPORTANT: A single document may contain MULTIPLE separate orders/invoices. 
    You MUST extract EACH order separately as its own object in the 'orders' list.
    
    CRITICAL INSTRUCTIONS:
    1. EXTRACT EVERY SINGLE LINE ITEM. Do not summarize.
    2. REPEATING ITEMS: If the same product appears in multiple rows (e.g., 11 units on one line, 1 unit on the next), EXTRACT BOTH ROWS SEPARATELY. Do not combine them yourself. and if the price is zero in one row leave it as zero.
    3. 'vat_status': Check if the column headers say "Price inc. VAT" (INCLUDED) or "Price exc. VAT" (EXCLUDED). default to EXCLUDED.
    4. GLOBAL DISCOUNT: Look for a discount at the BOTTOM of the invoice that applies to ALL items.
       - This may appear as "הנחה כללית", "הנחה", "discount", or a percentage like "15.25%".
       - Extract this as 'global_discount_percentage' (e.g., 10 for 10% off).
       - The 'final_net_price' for EACH line item must include this global discount!
    5. 'final_net_price' CALCULATION:
       - Start with 'raw_unit_price'.
       - Apply 'discount_percentage' (line level).
       - Apply 'global_discount_percentage' (invoice level).
       - VAT ADJUSTMENT:
         * If 'vat_status' is "EXCLUDED", do nothing more. default to EXCLUDED.
         * If 'vat_status' is "INCLUDED", divide by (1 + vat_rate/100).
           -> CRITICAL EXCEPTION: If 'global_discount_percentage' is between 15.1% and 15.5% (e.g. 15.25%), this discount IS the VAT removal. TREAT THIS AS ALREADY EXCLUDING VAT. Do NOT divide by (1 + vat_rate/100) again.
    6. 'document_total_with_vat': Extract the FINAL TOTAL amount at the bottom of the invoice (סה"כ לתשלום).
    7. 'vat_rate': If VAT rate is stated (18%, etc.), extract the number. Default to {VAT_RATE * 100}.
    8. 'document_total_quantity': Extract the TOTAL QUANTITY of items if stated at the bottom of the invoice (סה"כ כמות / פריטים).

    *** MANDATORY MATH SELF-CHECK ***
    Before finalizing the JSON, you MUST perform this internal calculation:
    1. For each line item: line_total = quantity * final_net_price
    2. Sum all line_total values.
    3. Apply VAT: grand_total = total_sum * (1 + vat_rate/100)
    4. Compare grand_total to the 'document_total_with_vat'.
    5. If they don't match (within 1.0) you have made a calculation or extraction error. 
       - RE-CHECK the quantities, unit prices, and discounts.
       - Ensure you converted 'INCLUDED' VAT prices to 'EXCLUDED' correctly.
    
    *** IMPORTANT: BARCODE EXTRACTION ***
    - You must find the column that contains the INTERNATIONAL BARCODE (EAN/GTIN).
    - These are typically 13-digit numbers (e.g., 7290000000000).
    - START by looking for a column with long numeric strings (12-14 digits).
    - DO NOT extract internal supplier codes (usually short, 3-6 digits) as the barcode.
    - If the product has multiple codes, ALWAYS PREFER THE LONGER 13-DIGIT SEQUENCE.
    - If no valid 12-14 digit barcode column exists, return null for the barcode field. Do NOT use internal codes (3-5 digits) or phone numbers as barcodes.
    
    Output must strictly follow the defined schema.
    """

    # Add supplier-specific instructions AFTER general instructions with PRIORITY
    if supplier_instructions:
        prompt_text += f"""
    
    ⚠️ SUPPLIER-SPECIFIC OVERRIDES (HIGHEST PRIORITY):
    The following instructions are specific to THIS supplier and OVERRIDE any conflicting rules above.
    If there is any conflict between the general instructions above and the supplier-specific instructions below,
    ALWAYS follow the supplier-specific instructions.
    
    {supplier_instructions}
    """
    
    # RETRY LOGIC: Add feedback if this is a retry
    current_tools = None
    current_schema = None
    
    # Define Schema for JSON Enforcement (Phase 2)
    single_order_schema = {
        "type": "OBJECT",
        "properties": {
            "invoice_number": {"type": "STRING", "nullable": True},
            "global_discount_percentage": {"type": "NUMBER", "nullable": True},
            "total_invoice_discount_amount": {"type": "NUMBER", "nullable": True},
            "document_total_with_vat": {"type": "NUMBER", "nullable": True},
            "document_total_quantity": {"type": "NUMBER", "nullable": True},
            "vat_rate": {"type": "NUMBER", "nullable": True},
            "line_items": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "barcode": {"type": "STRING", "nullable": True},
                        "description": {"type": "STRING"},
                        "quantity": {"type": "NUMBER", "nullable": True},
                        "raw_unit_price": {"type": "NUMBER", "nullable": True},
                        "vat_status": {"type": "STRING", "enum": ["INCLUDED", "EXCLUDED", "EXEMPT"]},
                        "discount_percentage": {"type": "NUMBER", "nullable": True},
                        "final_net_price": {"type": "NUMBER", "nullable": True}
                    },
                    "required": ["description", "vat_status"]
                }
            }
        },
        "required": ["line_items"]
    }

    pdf_response_schema = {
        "type": "OBJECT",
        "properties": {
            "orders": {
                "type": "ARRAY",
                "items": single_order_schema
            }
        },
        "required": ["orders"]
    }

    if retry_count > 0:
        print(f"⚠️ RETRY ATTEMPT {retry_count}: Adding feedback and ENABLING CODE EXECUTION.")
        prompt_text += f"""
    
    ⚠️ PREVIOUS ATTEMPT FAILED validation of totals.
    
    YOU MUST USE PYTHON CODE TO CALCULATE AND VERIFY THE TOTALS.
    1. Write Python code to sum the line items and check against the document total.
    2. Adjust your extraction if the math does not match.
    3. AFTER your code execution is finished and verified, output the FINAL JSON result.
    
    CRITICAL: The final JSON MUST include the full "orders" list with all extracted items.
    Do NOT output only a summary or just the totals. We need the COMPLETE JSON object.
    
    
    IMPORTANT: Since code execution is enabled, you must output the JSON result in a markdown block.
    
    You MUST strictly follow this JSON schema for your final output:
    ```json
    {json.dumps(pdf_response_schema, indent=2)}
    ```
    
    """
        # Enable Code Execution for retries (and disable schema to avoid conflict)
        current_tools = [types.Tool(code_execution=types.ToolCodeExecution())]
        current_schema = None 
    else:
        # Normal run: Use Schema for safety
        current_tools = None
        current_schema = pdf_response_schema

    print("Sending request to Gemini...")
    # NOTE: Removed try/except block here. Let exceptions bubble up to the caller
    # so they can be properly logged to the file (listener.log).
    
    # Use a more powerful model for retries
    model_name = "gemini-2.5-pro" if retry_count > 0 else "gemini-2.5-flash"
    print(f"Using model: {model_name}")

    response = generate_content_safe(
        model=model_name,
        contents=[
            types.Content(
                role="user",
                parts=[
                    file_part,
                    types.Part.from_text(text=prompt_text),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json" if current_schema else "text/plain",
            response_schema=current_schema,
            tools=current_tools,
            temperature=0.0
        )
    )

    raw_json = response.text
    
    # If using Code Execution (retry), we need to extract the JSON from the text response
    if retry_count > 0:
        # Look for JSON block
        if "```json" in raw_json:
            try:
                # Extract content between ```json and ```
                raw_json = raw_json.split("```json")[1].split("```")[0].strip()
            except IndexError:
                print("Warning: Failed to extract JSON from code execution response. Using raw text.")
        else:
             # Try simple clean in case it just outputted raw json
             raw_json = raw_json.replace("```json", "").replace("```", "").strip()

    # Cleanup (Standard)
    raw_json = raw_json.replace("```json", "").replace("```", "").strip()

    # Log structured JSON for Cloud Run
    try:
        parsed_json = json.loads(raw_json)
        # detailed log with event info
        log_payload = {
            "severity": "INFO", 
            "message": "AI Model Response (Phase 2)",
            "event_type": "ai_response",
            "json_payload": parsed_json
        }
        print(json.dumps(log_payload))
    except json.JSONDecodeError:
        # Fallback if AI returns invalid JSON
        log_payload = {
            "severity": "ERROR",
            "message": "AI Model Response (Phase 2) - Parse Error",
            "event_type": "ai_response_error",
            "raw_payload": raw_json
        }
        print(json.dumps(log_payload))

    print("Gemini response received. Validating...")
    multi_order = MultiOrderResponse.model_validate_json(raw_json)
    orders = multi_order.orders
    
    validated_orders = []
    
    for order in orders:
        # --- POST-PROCESSING: Handle 11+1 Promotions ---
        print(f"Running post-processing for promotions on order {order.invoice_number}...")
        order = post_process_promotions(order)
        
        # Filter out lines with 0 quantity (artifacts from relaxed validation)
        original_count = len(order.line_items)
        order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]
        filtered_count = len(order.line_items)
        
        if original_count != filtered_count:
            print(f"Filtered out {original_count - filtered_count} lines with 0 quantity.")
        
        print(f"Success! Extracted {len(order.line_items)} line items from supplier.")
        
        # --- VALIDATION: Check Totals ---
        print(f"Validating order totals for {order.invoice_number}...")
        is_valid, calc_total, diff = validate_order_totals(order)
        
        if not is_valid:
            warning_msg = (
                f"Validation Failed: Document Total ({order.document_total_with_vat:.2f}) "
                f"!= Calculated Total ({calc_total:.2f}). Diff: {diff:.2f}"
            )
            print(f"❌ {warning_msg}")
            
            # Final failure after retry (or first attempt if we didn't retry yet) - add warning to order
            # Note: Retrying multi-orders is slightly more complex, so for now we just log warnings
            # unless it's a critical total mismatch that triggers a whole-file retry.
            order.warnings.append(warning_msg)
            order.warnings.append(f"Calculated from lines: {calc_total:.2f} (VAT {VAT_RATE*100}%)")
        else:
            print(f"✅ Validation Passed! Diff: {diff:.2f} (Tolerance: {VALIDATION_TOLERANCE})")

        # --- VALIDATION: Check Quantities ---
        print(f"Validating order quantities for {order.invoice_number}...")
        is_valid_qty, calc_qty, diff_qty = validate_order_quantity(order)
        if not is_valid_qty:
            qty_warning = f"Quantity Validation Failed: Document Qty ({order.document_total_quantity}) != Sum ({calc_qty}). Diff: {diff_qty:.2f}"
            print(f"⚠️ {qty_warning}")
            order.warnings.append(qty_warning)
        else:
            print(f"✅ Quantity Validation Passed! Diff: {diff_qty:.2f}")

        validated_orders.append(order)

    # Global retry logic: If ANY order failed critical validation AND we have retries left
    # we retry the entire document extraction.
    critical_failure_found = any(
        "Validation Failed: Document Total" in w 
        for order in validated_orders 
        for w in order.warnings
    )
    
    if critical_failure_found and retry_count < MAX_RETRIES:
        print(f"⚠️ Critical validation failed for one or more orders. Retrying full extraction... (Attempt {retry_count + 1}/{MAX_RETRIES})")
        return process_invoice(
            file_path, 
            mime_type, 
            email_context, 
            supplier_instructions, 
            retry_count=retry_count + 1
        )
    
    return validated_orders
    
    if not is_valid_qty:
        warning_msg = (
            f"Quantity Validation Failed: Document Total ({order.document_total_quantity}) "
            f"!= Calculated Total ({calc_qty}). Diff: {diff_qty}"
        )
        print(f"❌ {warning_msg}")
        # We append warning but DO NOT RETRY for quantity mismatch as it's less critical than price
        # and often caused by "11+1" logic or unit differences (kg vs units)
        order.warnings.append(warning_msg)
    else:
        if order.document_total_quantity:
            print(f"✅ Quantity Validation Passed! Diff: {diff_qty}")

    return order

def post_process_promotions(order: ExtractedOrder) -> ExtractedOrder:
    """
    Handles split lines for "X+Y derived" promotions (e.g. 11+1).
    Logic:
    1. Group by barcode.
    2. If multiple lines exist for the same barcode:
       - Calculate total cost and total quantity.
       - Calculate weighted average price.
       - Apply this average price to ALL lines in the group (splitting the discount).
       - Keep lines separate (user request).
    """
    if not order.line_items:
        return order

    from collections import defaultdict
    grouped_items = defaultdict(list)
    
    # Group items by barcode
    for item in order.line_items:
        # Use a fallback key if barcode is missing, though usually required for merging logic
        key = item.barcode if item.barcode else f"NO_BARCODE_{item.description}"
        grouped_items[key].append(item)

    new_line_items = []
    
    for barcode, items in grouped_items.items():
        if len(items) == 1:
            new_line_items.extend(items)
            continue
            
        # We have potential duplicates/splits.
        total_qty = sum(item.quantity for item in items)
        total_cost = sum(item.quantity * item.final_net_price for item in items)
        
        if total_qty == 0:
            new_line_items.extend(items)
            continue
            
        # New weighted average price (Net Price)
        avg_net_price = total_cost / total_qty
        
        print(f"Applying avg price {avg_net_price:.2f} to {len(items)} lines for {barcode} (Total Qty: {total_qty})")
        
        for item in items:
            # Create copy to modify
            updated_item = item.model_copy()
            # Update price to the average
            updated_item.final_net_price = round(avg_net_price, 4)
            # Keep original quantity and description
            new_line_items.append(updated_item)
        
    order.line_items = new_line_items
    return order
