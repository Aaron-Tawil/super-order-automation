from google.genai import types

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
