import json

from src.extraction.schemas import pdf_response_schema
from src.shared.constants import VAT_RATE


def get_supplier_detection_prompt(filtered_email: str, invoice_context: str, suppliers_csv: str) -> str:
    """
    Returns the prompt for Phase 1: Supplier Detection.
    """
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
    return prompt


def get_invoice_extraction_prompt(
    email_context: str = None,
    supplier_instructions: str = None,
    version: str = "v1",
    enable_code_execution: bool = False,
) -> str:
    """
    Returns the prompt for Phase 2: Invoice Extraction.

    Args:
        email_context: Optional text from the email body.
        supplier_instructions: Optional supplier-specific instructions.
        version: Version of the prompt to use. Default is "v1".
        enable_code_execution: If True, adds instructions for code execution and math verification.
    """

    if version == "v1":
        return _get_invoice_extraction_prompt_v1(email_context, supplier_instructions, enable_code_execution)
    elif version == "v2":
        return _get_invoice_extraction_prompt_v2(email_context, supplier_instructions)
    else:
        raise ValueError(f"Unknown prompt version: {version}")


def _get_invoice_extraction_prompt_v1(
    email_context: str, supplier_instructions: str, enable_code_execution: bool
) -> str:
    prompt_text = ""
    if email_context:
        prompt_text += f"""
    CONTEXT FROM EMAIL BODY:
    {email_context}
    
    """

    prompt_text += f"""
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
    7. 'vat_rate': ALWAYS return {VAT_RATE * 100}. Ignore any other VAT rate stated on the document.
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

    if enable_code_execution:
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

    return prompt_text


def _get_invoice_extraction_prompt_v2(email_context: str, supplier_instructions: str) -> str:
    """
    Simplified prompt (v2) focusing on RAW DATA EXTRACTION only.
    No complex math or self-checking requested from the LLM.
    Calculations will be done in Python post-processing.
    """
    prompt_text = ""
    if email_context:
        prompt_text += f"""
    CONTEXT FROM EMAIL BODY:
    {email_context}
    
    """

    prompt_text += f"""
    You are an expert data extraction assistant for an Accounting team.
    Your job is to EXTRACT THE RAW DATA EXACTLY AS PRINTED on the document. Do NOT perform ANY calculations.
    Do NOT convert prices. Do NOT remove VAT. Do NOT adjust values. Just read what is written.
    
    IMPORTANT: A single document may contain MULTIPLE separate orders/invoices. 
    You MUST extract EACH order separately as its own object in the 'orders' list.
    
    CRITICAL EXTRACTION RULES:
    1. EXTRACT EVERY SINGLE LINE ITEM. Do not summarize.
    2. REPEATING ITEMS: If the same product appears in multiple rows, EXTRACT BOTH ROWS SEPARATELY.
    3. 'vat_status': Check columns for "Price inc. VAT" / "כולל מע"מ" (INCLUDED) or "Price exc. VAT" / "לפני מע"מ" (EXCLUDED). Default is EXCLUDED.
       - IMPORTANT: Just REPORT whether the price column includes VAT or not. Do NOT convert the price.
    4. GLOBAL DISCOUNT: Look for a general discount at the BOTTOM of the invoice (e.g., "הנחה: 15.25%", "הנחה כללית", "discount").
       - If a PERCENTAGE is shown (e.g., "15.25 %"), extract it into 'global_discount_percentage'.
       - If a monetary AMOUNT is shown (e.g., "648.35"), extract it into 'total_invoice_discount_amount'.
       - Extract BOTH if both are shown.
       - IMPORTANT: If the SUPPLIER-SPECIFIC INSTRUCTIONS below mention a global discount that is NOT
         explicitly shown on the document, you MUST still set 'global_discount_percentage' accordingly.
    
    5. LINE ITEM DETAILS:
       - 'raw_unit_price': THE EXACT NUMBER in the price/מחיר column. DO NOT divide by VAT, DO NOT apply
         any discount, DO NOT calculate anything. Just copy the number as printed.
         Example: if the column says 20.50, return 20.50. NOT 17.37 (which would be 20.50/1.18).
       - 'discount_percentage': Extract line-level discount percentage if shown (the number in הנחה column).
       - 'final_net_price': LEAVE NULL. We will calculate this ourselves in post-processing.
    
    6. DOCUMENT TOTALS (For Validation):
       - 'document_total_with_vat': Extract the FINAL TOTAL to pay (סה"כ לתשלום).
         * EXCEPTION: If you applied a global discount from SUPPLIER-SPECIFIC INSTRUCTIONS that is NOT
           already reflected in the document total, you MUST recalculate 'document_total_with_vat' by
           applying that discount to the original total.
       - 'document_total_quantity': Extract TOTAL QUANTITY ONLY if explicitly printed on the document
         (e.g., "סה"כ כמות: 510"). If no total quantity line exists, return null. Do NOT sum up quantities yourself.
       - 'vat_rate': ALWAYS return {VAT_RATE * 100}. Ignore any other VAT rate stated on the document.

    *** IMPORTANT: BARCODE EXTRACTION ***
    - Look for INTERNATIONAL BARCODE (EAN/GTIN), typically 13 digits.
    - Prefer 12-14 digit numbers over short internal codes.
    - If no barcode column exists, return null.

    Output must strictly follow the defined schema.
    """

    if supplier_instructions:
        prompt_text += f"""
    
    ⚠️ SUPPLIER-SPECIFIC OVERRIDES (HIGHEST PRIORITY):
    {supplier_instructions}
    """

    return prompt_text
