import json

from src.extraction.schemas import calc_response_schema, raw_response_schema
from src.shared.config import settings
from src.shared.constants import VALIDATION_TOLERANCE, VAT_RATE


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
5. IGNORE OUR COMPANY: Never match ourselves as a supplier.
   - Ignore IDs (H.P./Osek Murshe): {", ".join(settings.blacklist_ids)}
   - Ignore Company Names: {", ".join(settings.blacklist_names)}
   - If a document contains both a supplier and our name (as the bill-to party), ALWAYS pick the OTHER party as the supplier.
6. If you find a clear match, return the supplier code.
7. If you cannot find a confident match, return "UNKNOWN".

8. Extract the SUPPLIER'S EMAIL ADDRESS if found in the document or email body.
   - Return it in the `detected_email` field.
   - If multiple emails found, prefer the one in the invoice header or footer.
   - If no email found, return null.

9. Extract the SUPPLIER'S GLOBAL ID (Tax ID / BN / Osek Murshe / H.P) if found.
   - Return it in the `detected_id` field.
   - It usually looks like a 9-digit number.
   - If not found, return null.

10. LANGUAGE REQUIREMENT: Return the `reasoning` field in Hebrew.

Output must strictly follow the defined schema.
"""
    return prompt


def get_invoice_extraction_prompt(
    email_context: str = None,
    supplier_instructions: str = None,
    trial: int = 1,
) -> str:
    """
    Returns the prompt for Phase 2: Invoice Extraction.

    Args:
        email_context: Optional text from the email body.
        supplier_instructions: Optional supplier-specific instructions.
        trial: Which trial version to run (1 = Raw Data, 2 = LLM Calculated).
    """

    if trial == 1:
        return _get_invoice_extraction_prompt_trial_1(email_context, supplier_instructions)
    elif trial == 2:
        return _get_invoice_extraction_prompt_trial_2(email_context, supplier_instructions)
    else:
        raise ValueError(f"Unknown prompt trial version: {trial}")


def _get_invoice_extraction_prompt_trial_1(email_context: str, supplier_instructions: str) -> str:
    """
    Trial 1 Prompt (Raw Data Extraction).
    Instructs the LLM NOT to do math. Just copy what is on the page.
    """
    prompt_text = ""
    if email_context:
        prompt_text += f"""
    CONTEXT FROM EMAIL BODY:
    {email_context}
    
    """

    prompt_text += """
    You are an expert data extraction assistant for an Accounting team.
    Your job is to EXTRACT THE RAW DATA EXACTLY AS PRINTED on the document. Do NOT perform ANY calculations (unless specified in the BIG EXCEPTION below).
    Do NOT convert prices. Do NOT remove VAT. Do NOT adjust values. Just read what is written.
    
    IMPORTANT: A single document may contain MULTIPLE separate orders/invoices. 
    You MUST extract EACH order separately as its own object in the 'orders' list.
    
    CRITICAL EXTRACTION RULES:
    1. COLUMN IDENTIFICATION: Look closely at the header columns to determine which field is 'quantity' (כמות), 'discount' (הנחה), and 'price' (מחיר). Do NOT be confused by other columns like "Total per row" (סה"כ), "Net total" or other calculated fields.
    2. EXTRACT EVERY SINGLE LINE ITEM. Do not summarize.
    3. REPEATING ITEMS: If the same product appears in multiple rows, EXTRACT BOTH ROWS SEPARATELY.
    4. 'vat_status': Check columns for "Price inc. VAT" / "כולל מע"מ" (INCLUDED) or "Price exc. VAT" / "לפני מע"מ" (EXCLUDED). if not stated - assume EXCLUDED. defaults to EXCLUDED.
       - IMPORTANT: Just REPORT whether the price column includes VAT or not. Do NOT convert the price yourself.
    5. GLOBAL DISCOUNT: Look for a general discount at the BOTTOM of the invoice (e.g., "הנחה: 15.25%", "הנחה כללית", "discount").
       - If a PERCENTAGE is shown (e.g., "15.25 %"), extract it into 'global_discount_percentage'.
       - If a monetary AMOUNT is shown (e.g., "648.35"), extract it into 'total_invoice_discount_amount'.
       - Extract BOTH if both are shown.
       - IMPORTANT: If the SUPPLIER-SPECIFIC INSTRUCTIONS below mention a global discount that is NOT
         explicitly shown on the document, you MUST still set 'global_discount_percentage' accordingly.
    
    6. LINE ITEM DETAILS:
       - 'raw_unit_price': THE EXACT NUMBER in the price/מחיר column. DO NOT divide by VAT, DO NOT apply
         any discount, DO NOT calculate anything. Just copy the number as printed.
       - 'discount_percentage': Extract line-level discount percentage if shown (the number in הנחה column).
       - 'quantity': Extract the quantity for this line item.
       - 'barcode': Extract the barcode for this line item.
       - 'description': Extract the description for this line item.
       - 'vat_status': Apply the VAT status determined above ("INCLUDED" or "EXCLUDED").
       
    
    7. DOCUMENT TOTALS (For Validation):
       - 'document_total_with_vat': Extract the FINAL TOTAL to pay (סה"כ לתשלום).
         *** BIG EXCEPTION (The ONLY cases where you recalculate this value): ***
         1. VAT CORRECTION: If the document states 17% VAT, it is a mistake. You MUST calculate the total for 18% VAT instead.
         2. MISSING GLOBAL DISCOUNT: If the SUPPLIER-SPECIFIC INSTRUCTIONS mention a global discount that is NOT explicitly shown or reflected in the document's printed totals, you MUST recalculate 'document_total_with_vat' to reflect it.
         Otherwise, just copy the value exactly as printed.
       - 'document_total_without_vat': Extract the FINAL PRE-VAT TOTAL (סה"כ לפני מע"מ).
         - IMPORTANT: This field must represent the total AFTER any global discount but BEFORE VAT.
         - *** BIG EXCEPTION: *** If the SUPPLIER-SPECIFIC INSTRUCTIONS mention a global discount that is NOT explicitly reflected in the document's printed totals, you MUST recalculate 'document_total_without_vat' to reflect it.
       - 'document_total_quantity': Extract TOTAL QUANTITY ONLY if explicitly printed on the document
         (e.g., "סה"כ כמות: 510"). If no total quantity line exists, return null. Do NOT sum up quantities yourself.

    8. 'notes': Use this field for any AI-GENERATED observations, explanations, or internal comments about your extraction process.
       - IMPORTANT: Do NOT copy general notes, shipping instructions, or terms already printed on the supplier's invoice. This field is for YOUR thoughts, not for document text.
       - If no specific observations are needed, leave this field as null or an empty string.
       - LANGUAGE REQUIREMENT: Return this field in Hebrew.
    
    *** IMPORTANT: BARCODE EXTRACTION ***
    - Look for INTERNATIONAL BARCODE (EAN/GTIN), typically 13 digits.
    - Prefer 12-14 digit numbers over short internal codes.
    - If no barcode column exists, return null.

    CRITICAL: Output ONLY the final JSON object. Do NOT include any preamble, conversational text, or explanations outside the JSON block.
    """

    if supplier_instructions:
        prompt_text += f"""
    
    ⚠️ SUPPLIER-SPECIFIC OVERRIDES (HIGHEST PRIORITY):
    {supplier_instructions}
    """

    return prompt_text


def _get_invoice_extraction_prompt_trial_2(email_context: str, supplier_instructions: str) -> str:
    """
    Trial 2 Prompt (LLM Calculated Data).
    Instructs the LLM to write code, do the math, and provide ONLY the final net prices.
    """
    prompt_text = ""
    if email_context:
        prompt_text += f"""
    CONTEXT FROM EMAIL BODY:
    {email_context}
    
    """

    prompt_text += f"""
    You are an expert data extraction assistant for an Accounting team.
    
    ⚠️ PREVIOUS ATTEMPT FAILED. The mathematically calculated totals did not match the document total.
    
    In this attempt, we need you to figure out the exact mathematical `final_net_price` for each item.
    
    CRITICAL INSTRUCTIONS:
    1. COLUMN IDENTIFICATION: Look closely at the header columns to determine which field is 'quantity' (כמות), 'discount' (הנחה), and 'price' (מחיר). Do NOT be confused by other columns like "Total per row" (סה"כ שורה), "Net total" or other calculated fields.
    2. EXTRACT EVERY SINGLE LINE ITEM. Do not summarize.
    3. REPEATING ITEMS: If the same product appears in multiple rows, EXTRACT BOTH ROWS SEPARATELY.
    4. `final_net_price` CALCULATION REQUIREMENT:
       - You must determine the FINAL NET PRICE for each item. 
       - This means applying ALL line discounts, ALL global discounts (e.g. 15.25% if found or specified), and REMOVING VAT if the printed price included it.
       - The value you provide must be the pure net cost per unit.
    5. Provide ONLY the final calculated net price in the JSON schema (`final_net_price`).
    
    *** VALIDATION COPY FIELDS (DO NOT CALCULATE) ***
    The following fields are for mathematical validation. You MUST copy them EXACTLY as printed on the document (unless specified in the BIG EXCEPTION below). Do NOT calculate them yourself.
    6. 'document_total_with_vat': COPY the FINAL TOTAL amount at the bottom of the invoice (סה"כ לתשלום).
       *** BIG EXCEPTION (The ONLY cases where you recalculate this value): ***
       1. VAT CORRECTION: If the document states 17% VAT, it is a mistake. You MUST calculate the total for 18% VAT instead.
       2. MISSING GLOBAL DISCOUNT: If the SUPPLIER-SPECIFIC INSTRUCTIONS mention a global discount that is NOT explicitly shown or reflected in the document's printed totals, you MUST recalculate 'document_total_with_vat' to reflect it.
       Otherwise, just copy the value exactly as printed.
    7. 'document_total_without_vat': COPY the FINAL PRE-VAT TOTAL (סה"כ לפני מע"מ).
       - IMPORTANT: This field must represent the total AFTER any global discount but BEFORE VAT.
       - *** BIG EXCEPTION: *** If the SUPPLIER-SPECIFIC INSTRUCTIONS mention a global discount that is NOT explicitly reflected in the document's printed totals, you MUST recalculate 'document_total_without_vat' to reflect it.
    8. 'document_total_quantity': COPY the TOTAL QUANTITY ONLY if explicitly printed on the document.
    9. 'notes': Use this field for any AI-GENERATED observations, explanations, or internal comments about your extraction process or discrepancies you found.
       - IMPORTANT: Do NOT copy general notes, shipping instructions, or terms already printed on the supplier's invoice. This field is for YOUR thoughts, not for document text.
       - If no specific observations are needed, leave this field as null or an empty string.
    10. LANGUAGE REQUIREMENT: All text fields intended for human reading (`notes`, `math_reasoning`, `qty_reasoning`) MUST be returned in Hebrew.

    *** MANDATORY MATH VERIFICATION (CODE EXECUTION) ***
    YOU MUST USE PYTHON CODE TO CALCULATE AND VERIFY THE TOTALS BEFORE ANSWERING.
    1. Write Python code to sum up your calculated line items: `sum(quantity * final_net_price)`.
    2. Apply VAT to your sum: `total_net * (1 + {VAT_RATE})`.
    3. Compare your calculated gross total to the `document_total_with_vat`.
    4. Provide the boolean result in `is_math_valid`.
       - IMPORTANT: If the difference between your calculated total and the `document_total_with_vat` is less than or equal to {VALIDATION_TOLERANCE}, you MUST mark `is_math_valid` as true.
    5. If the math does NOT balance (difference > {VALIDATION_TOLERANCE}), explain exactly why in `math_reasoning` (e.g., "Missing a 10 NIS delivery fee", "Discount applied to wrong items").
       - IMPORTANT: Write this explanation in Hebrew.
    6. Compare your sum of quantities to the `document_total_quantity`.
    7. Provide the boolean result in `is_qty_valid` and any explanation in `qty_reasoning`.
       - IMPORTANT: Write this explanation in Hebrew.
    8. AFTER your code execution is finished and verified, output the FINAL JSON result.
    
    CRITICAL: Output ONLY the final JSON object. Do NOT include any preamble, conversational text, or explanations outside the JSON block.
    The final JSON MUST include the full "orders" list with all extracted items.
    Do NOT output only a summary or just the totals. We need the COMPLETE JSON object.
    
    IMPORTANT: Since code execution is enabled, you must output the JSON result in a markdown block.
    
    You MUST strictly follow this JSON schema for your final output:
    ```json
    {json.dumps(calc_response_schema, indent=2)}
    ```

    *** IMPORTANT: BARCODE EXTRACTION ***
    - Look for INTERNATIONAL BARCODE (EAN/GTIN), typically 13 digits.
    - Prefer 12-14 digit numbers over short internal codes.
    - If no barcode column exists, return null.
    """

    if supplier_instructions:
        prompt_text += f"""
    
    ⚠️ SUPPLIER-SPECIFIC OVERRIDES (HIGHEST PRIORITY):
    The following instructions are specific to THIS supplier and OVERRIDE any conflicting rules above.
    If there is any conflict between the general instructions above and the supplier-specific instructions below,
    ALWAYS follow the supplier-specific instructions.
    
    {supplier_instructions}
    """

    return prompt_text
