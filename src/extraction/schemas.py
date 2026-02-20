from google.genai import types

# Define Schema for Trial 1: Raw Data Extraction (No Math)
raw_line_item_schema = {
    "type": "OBJECT",
    "properties": {
        "barcode": {"type": "STRING", "nullable": True},
        "description": {"type": "STRING"},
        "quantity": {"type": "NUMBER", "nullable": True},
        # Raw Data ONLY
        "raw_unit_price": {"type": "NUMBER", "nullable": True},
        "vat_status": {"type": "STRING", "enum": ["INCLUDED", "EXCLUDED"]},
        "discount_percentage": {"type": "NUMBER", "nullable": True},
    },
    "required": ["description", "vat_status"],
}

raw_order_schema = {
    "type": "OBJECT",
    "properties": {
        "invoice_number": {"type": "STRING", "nullable": True},
        # Invoice-level financials
        "global_discount_percentage": {"type": "NUMBER", "nullable": True},
        "total_invoice_discount_amount": {"type": "NUMBER", "nullable": True},
        "document_total_with_vat": {"type": "NUMBER", "nullable": True},
        "document_total_without_vat": {"type": "NUMBER", "nullable": True},
        "document_total_quantity": {"type": "NUMBER", "nullable": True},
        "notes": {"type": "STRING", "nullable": True},
        "line_items": {
            "type": "ARRAY",
            "items": raw_line_item_schema,
        },
    },
    "required": ["line_items"],
}

raw_response_schema = {
    "type": "OBJECT",
    "properties": {"orders": {"type": "ARRAY", "items": raw_order_schema}},
    "required": ["orders"],
}

# Define Schema for Trial 2: LLM Calculated Extraction (Math Enforced)
calc_line_item_schema = {
    "type": "OBJECT",
    "properties": {
        "barcode": {"type": "STRING", "nullable": True},
        "description": {"type": "STRING"},
        "quantity": {"type": "NUMBER", "nullable": True},
        # LLM calculates this internally and provides the final result
        "final_net_price": {"type": "NUMBER", "nullable": True},
    },
    "required": ["description"],
}

calc_order_schema = {
    "type": "OBJECT",
    "properties": {
        "invoice_number": {"type": "STRING", "nullable": True},
        # Simplified validation totals
        "document_total_with_vat": {"type": "NUMBER", "nullable": True},
        "document_total_without_vat": {"type": "NUMBER", "nullable": True},
        "document_total_quantity": {"type": "NUMBER", "nullable": True},
        "notes": {"type": "STRING", "nullable": True},
        # LLM Verification
        "is_math_valid": {"type": "BOOLEAN"},
        "math_reasoning": {"type": "STRING", "nullable": True},
        "is_qty_valid": {"type": "BOOLEAN"},
        "qty_reasoning": {"type": "STRING", "nullable": True},
        "line_items": {
            "type": "ARRAY",
            "items": calc_line_item_schema,
        },
    },
    "required": ["line_items"],
}

calc_response_schema = {
    "type": "OBJECT",
    "properties": {"orders": {"type": "ARRAY", "items": calc_order_schema}},
    "required": ["orders"],
}

# Define Schema for Phase 1: Supplier Detection
supplier_detection_schema = {
    "type": "OBJECT",
    "properties": {
        "supplier_code": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
        "detected_email": {"type": "STRING", "nullable": True},
        "detected_id": {"type": "STRING", "nullable": True},
    },
    "required": ["supplier_code", "confidence", "reasoning"],
}
