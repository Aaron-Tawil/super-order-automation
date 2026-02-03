from google import genai
from google.genai import types
import os
import re
from typing import Optional, Tuple
import sys
import pandas as pd
import io

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.shared.models import ExtractedOrder
from src.shared.constants import VAT_RATE, VALIDATION_TOLERANCE

# Emails to exclude from supplier detection context
EXCLUDED_EMAILS = [
    "store4@superhome.co.il",
    "moishiop@gmail.com"
]

# Path to supplier database
SUPPLIERS_EXCEL_PATH = os.path.join(
    os.path.dirname(__file__), 
    '../../data-excel/suppliers.xlsx'
)

# Global client variable
_client = None

def init_client(project_id: str = None, location: str = "us-central1", api_key: str = None):
    """
    Initialize the Gen AI Client.
    Priority:
    1. API Key (Google AI Studio) - Recommended for testing/MVP
    2. Vertex AI (GCP Project) - Recommended for Production
    """
    global _client
    
    if api_key:
        print("Initializing Gen AI Client with API KEY (AI Studio mode)...")
        _client = genai.Client(api_key=api_key)
    elif project_id:
        print(f"Initializing Gen AI Client with VERTEX AI (Project: {project_id})...")
        _client = genai.Client(
            vertexai=True, 
            project=project_id, 
            location=location
        )
    else:
        print("Error: Must provide either api_key OR project_id.")


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
                df = pd.read_excel(invoice_file_path)
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
   - Company name
   - Phone number
   - Email address
   - Business ID (עוסק/ח"פ) - usually a 9-digit number
   - Logo or letterhead text
2. Match these identifiers to the supplier database.
3. The supplier "קוד" (code) column is what you need to return.
4. Prioritize matches from the invoice over email if there's a conflict.
5. If you find a clear match, return the supplier code.
6. If you cannot find a confident match, return "UNKNOWN".

Return your response in this exact JSON format:
{{
    "supplier_code": "string (the קוד value from the database, or UNKNOWN)",
    "confidence": float (0.0 to 1.0, how confident you are in the match),
    "reasoning": "string (brief explanation of how you matched)"
}}
"""
    
    # Add text prompt
    content_parts.append(types.Part.from_text(text=prompt))
    
    print("Phase 1: Detecting supplier from email + invoice context...")
    
    try:
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=content_parts
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
        )
        
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        
        import json
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

def process_invoice(file_path: str, mime_type: str = None, email_context: str = None, supplier_instructions: str = None, retry_count: int = 0) -> Optional[ExtractedOrder]:
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
        return None

    # Handle Excel files by converting to text (CSV)
    excel_mime_types = [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ]
    
    file_part = None
    
    if mime_type in excel_mime_types:
        print(f"Excel detected ({mime_type}). Converting to CSV text for Gemini...")
        try:
            df = pd.read_excel(file_path)
            # Convert to CSV string
            csv_text = df.to_csv(index=False)
            file_part = types.Part.from_text(text=csv_text)
            print("Successfully converted Excel to CSV text.")
        except Exception as e:
            print(f"Error converting Excel file: {e}")
            return None
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
    
    CRITICAL INSTRUCTIONS:
    1. EXTRACT EVERY SINGLE LINE ITEM. Do not summarize.
    2. REPEATING ITEMS: If the same product appears in multiple rows (e.g., 11 units on one line, 1 unit on the next), EXTRACT BOTH ROWS SEPARATELY. Do not combine them yourself.
    3. 'vat_status': Check if the column headers say "Price inc. VAT" (INCLUDED) or "Price exc. VAT" (EXCLUDED).
    4. GLOBAL DISCOUNT: Look for a discount at the BOTTOM of the invoice that applies to ALL items.
       - This may appear as "הנחה כללית", "הנחה", "discount", or a percentage like "15.25%".
       - Extract this as 'global_discount_percentage' (e.g., 15.25 for 15.25% off).
       - The 'final_net_price' for EACH line item must include this global discount!
    5. 'final_net_price' CALCULATION:
       - Start with 'raw_unit_price'.
       - Apply 'discount_percentage' (line level).
       - Apply 'global_discount_percentage' (invoice level).
       - VAT ADJUSTMENT:
         * If 'vat_status' is "EXCLUDED", do nothing more.
         * If 'vat_status' is "INCLUDED", divide by (1 + vat_rate/100).
           -> CRITICAL EXCEPTION: If 'global_discount_percentage' is between 15.1% and 15.5% (e.g. 15.25%), this discount IS the VAT removal. TREAT THIS AS ALREADY EXCLUDING VAT. Do NOT divide by (1 + vat_rate/100) again.
    6. 'document_total_with_vat': Extract the FINAL TOTAL amount at the bottom of the invoice (סה"כ לתשלום).
    7. 'vat_rate': If VAT rate is stated (17%, 18%, etc.), extract the number. Default to {VAT_RATE * 100}.

    *** MANDATORY MATH SELF-CHECK ***
    Before finalizing the JSON, you MUST perform this internal calculation:
    1. For each line item: line_total = quantity * final_net_price
    2. Sum all line_total values.
    3. Apply VAT: grand_total = total_sum * (1 + vat_rate/100)
    4. Compare grand_total to the 'document_total_with_vat'.
    5. If they don't match (within 0.05), you have made a calculation or extraction error. 
       - RE-CHECK the quantities, unit prices, and discounts.
       - Ensure you converted 'INCLUDED' VAT prices to 'EXCLUDED' correctly.
    
    *** IMPORTANT: BARCODE EXTRACTION ***
    - You must find the column that contains the INTERNATIONAL BARCODE (EAN/GTIN).
    - These are typically 13-digit numbers (e.g., 7290000000000).
    - START by looking for a column with long numeric strings (12-14 digits).
    - DO NOT extract internal supplier codes (usually short, 3-6 digits) as the barcode.
    - If the product has multiple codes, ALWAYS PREFER THE LONGER 13-DIGIT SEQUENCE.
    
    Return valid JSON matching this structure exactly:
    {
      "invoice_number": "string",
      "global_discount_percentage": float (invoice-level discount as percentage, e.g., 15.25 for 15.25%),
      "total_invoice_discount_amount": float (the absolute discount amount if shown),
      "document_total_with_vat": float or null (final invoice total),
      "vat_rate": float (VAT percentage, default {VAT_RATE * 100}),
      "line_items": [
        {
          "barcode": "string (The 13-digit global barcode. Ignore short internal codes. Remove spaces/hyphens)",
          "description": "string (product name)",
          "quantity": float (total units for this specific line),
          "raw_unit_price": float (price as listed in the table),
          "vat_status": "INCLUDED" or "EXCLUDED",
          "discount_percentage": float (line-specific discount only),
          "paid_quantity": float or null (if explicitly stated),
          "bonus_quantity": float or null (if explicitly stated),
          "final_net_price": float (unit net AFTER global discount and excluding VAT)
        }
      ]
    }
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
    if retry_count > 0:
        print(f"⚠️ RETRY ATTEMPT {retry_count}: Adding feedback on failure.")
        prompt_text += f"""
    
    ⚠️ PREVIOUS ATTEMPT FAILED 
    The previous extraction had a mismatch between the line items total and the document total.
    Please be extremely careful with decimal places and ensuring that 'final_net_price' is calculated correctly.
    """

    print("Sending request to Gemini 2.5 Flash...")
    # NOTE: Removed try/except block here. Let exceptions bubble up to the caller
    # so they can be properly logged to the file (listener.log).
    
    response = _client.models.generate_content(
        model="gemini-2.5-flash",
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
            response_mime_type="application/json",
            temperature=0.0
        )
    )

    raw_json = response.text
    # Cleanup
    raw_json = raw_json.replace("```json", "").replace("```", "").strip()

    # --- DEBUG: Log Response ---
    # TODO: Remove this after debugging
    print(f"DEBUG_RAW_JSON_START\n{raw_json}\nDEBUG_RAW_JSON_END")
    # ---------------------------

    print("Gemini response received. Validating...")
    order = ExtractedOrder.model_validate_json(raw_json)
    
    # --- POST-PROCESSING: Handle 11+1 Promotions ---
    print("Running post-processing for promotions...")
    order = post_process_promotions(order)
    
    # Filter out lines with 0 quantity (artifacts from relaxed validation)
    original_count = len(order.line_items)
    order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]
    filtered_count = len(order.line_items)
    
    if original_count != filtered_count:
        print(f"Filtered out {original_count - filtered_count} lines with 0 quantity.")
    
    print(f"Success! Extracted {len(order.line_items)} line items from supplier.")
    
    # --- VALIDATION: Check Totals ---
    print("Validating order totals...")
    is_valid, calc_total, diff = validate_order_totals(order)
    
    if not is_valid:
        warning_msg = (
            f"Validation Failed: Document Total ({order.document_total_with_vat:.2f}) "
            f"!= Calculated Total ({calc_total:.2f}). Diff: {diff:.2f}"
        )
        print(f"❌ {warning_msg}")
        
        # RETRY if we haven't already
        if retry_count < 1:
            print("Triggering RETRY with feedback to AI...")
            return process_invoice(
                file_path, 
                mime_type, 
                email_context, 
                supplier_instructions, 
                retry_count=retry_count + 1
            )
        else:
            # Final failure after retry - add warning to order
            print("Max retries reached. Adding warning to order.")
            order.warnings.append(warning_msg)
            order.warnings.append(f"Calculated from lines: {calc_total:.2f} (VAT {VAT_RATE*100}%)")
    else:
        print(f"✅ Validation Passed! Diff: {diff:.2f} (Tolerance: {VALIDATION_TOLERANCE})")

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
