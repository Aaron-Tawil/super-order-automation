import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Force UTF-8 encoding for stdout to handle emojis and Hebrew on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from src.extraction.vertex_client import init_client, process_invoice, detect_supplier
from src.data.supplier_service import SupplierService

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_multi_order_extraction():
    # Load env vars
    from dotenv import load_dotenv
    load_dotenv()
    
    API_KEY = os.getenv("GEMINI_API_KEY")
    PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
    
    if not API_KEY and not PROJECT_ID:
        print("Error: Missing GEMINI_API_KEY or GCP_PROJECT_ID")
        return

    # Initialize client
    init_client(api_key=API_KEY, project_id=PROJECT_ID)
    
    pdf_path = r"c:\Dev\super-order-automation\tests-data\itel-multi-orders-in one-doc.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"Error: PDF not found at {pdf_path}")
        return

    print(f"Testing extraction from: {pdf_path}")
    
    # Phase 1: Supplier Detection
    supplier_code, confidence = detect_supplier(
        email_body="Attached are some orders for processing.",
        invoice_file_path=pdf_path,
        invoice_mime_type="application/pdf"
    )
    print(f"Detected Supplier: {supplier_code} (Confidence: {confidence})")
    
    # Phase 2: Extraction
    supplier_service = SupplierService()
    instructions = supplier_service.get_supplier_instructions(supplier_code) if supplier_code != "UNKNOWN" else None
    
    orders = process_invoice(
        pdf_path,
        mime_type="application/pdf",
        email_context="N/A",
        supplier_instructions=instructions
    )
    
    print(f"\nExtracted {len(orders)} orders.")
    
    for i, order in enumerate(orders):
        print(f"\nOrder {i+1}:")
        print(f"  Invoice Number: {order.invoice_number}")
        print(f"  Total with VAT: {order.document_total_with_vat}")
        print(f"  Line Items: {len(order.line_items)}")
        if order.warnings:
            print(f"  Warnings: {order.warnings}")
        
        # Verify first few items
        for j, item in enumerate(order.line_items[:2]):
            print(f"    Item {j+1}: {item.description} - Qty: {item.quantity}, Price: {item.final_net_price}")

if __name__ == "__main__":
    test_multi_order_extraction()
