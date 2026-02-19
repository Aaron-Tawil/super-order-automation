
import json
import logging
import os
import shutil
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.processor import OrderProcessor
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import filter_new_items_from_order, generate_new_items_excel
from src.extraction.vertex_client import detect_supplier, init_client
from src.shared.ai_cost import calculate_cost_ils, get_usd_to_ils_rate

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_pipeline(file_path):
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    # Create Output Directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = os.path.join(os.path.dirname(__file__), "output", f"{base_name}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("🚀 Starting Local Pipeline Test")
    logger.info(f"📂 Input File: {file_path}")
    logger.info(f"📂 Output Directory: {output_dir}")
    
    # Copy original file to output
    shutil.copy(file_path, output_dir)

    # Init Services
    init_client()
    items_service = ItemsService()
    supplier_service = SupplierService()
    
    # Check Currency Rate
    rate = get_usd_to_ils_rate()
    logger.info(f"💱 Live USD to ILS Rate: {rate}")

    # --- Phase 0: Local Supplier Detection ---
    logger.info(">>> Phase 0: Local Supplier Detection...")
    from src.extraction.local_detector import LocalSupplierDetector
    local_detector = LocalSupplierDetector()
    
    mime_type = "application/pdf" if file_path.lower().endswith(".pdf") else "application/octet-stream"
    if file_path.lower().endswith(".xlsx"):
         mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Mock Email Metadata for local test (can be customized if needed)
    mock_email_meta = {
        "sender": "example@supplier.com", 
        "subject": f"Invoice for {os.path.basename(file_path)}",
        "body": "Please find attached."
    }
    
    detected_code, confidence, method = local_detector.detect_supplier(
        file_path=file_path,
        mime_type=mime_type,
        email_metadata=mock_email_meta
    )
    
    cost_p1 = 0.0
    raw_data_p1 = {}

    if detected_code != "UNKNOWN":
        logger.info(f"✅ Supplier Locally Detected via {method}: {detected_code} (Conf: {confidence})")
        logger.info("Skipping Phase 1 (AI)...")
    else:
        # --- Phase 1: Supplier Detection (AI) ---
        logger.info("⚠️ Local detection failed. Proceeding to Phase 1 (AI)...")
        detected_code, confidence, cost_p1, _, raw_data_p1, detected_email, detected_id = detect_supplier(
            email_body="Attached is the invoice.",
            invoice_file_path=file_path,
            invoice_mime_type=mime_type
        )
        logger.info(f"Phase 1 Cost: ${cost_p1:.6f}")
        
        if detected_email:
             logger.info(f"📧 AI Detected Email: {detected_email}")
        if detected_id:
             logger.info(f"🆔 AI Detected ID: {detected_id}")
             # Simulate Auto-Learning
             if detected_code != "UNKNOWN":
                 logger.info(f"🧠 [SIMULATION] Would attempt to link {detected_email} to {detected_code}")

    # Save Phase 1 Raw Response
    p1_path = os.path.join(output_dir, "phase1_supplier.json")
    with open(p1_path, "w", encoding="utf-8") as f:
        json.dump(raw_data_p1, f, indent=4, ensure_ascii=False)
    logger.info(f"📄 Saved Phase 1 Raw Response: {p1_path}")
    
    supplier_name = "Unknown"
    supplier_instructions = None
    if detected_code != "UNKNOWN":
        s_data = supplier_service.get_supplier(detected_code)
        if s_data:
            supplier_name = s_data.get("name", "Unknown")
            supplier_instructions = s_data.get("special_instructions")
            logger.info(f"✅ Supplier Identified: {supplier_name} ({detected_code}) (Conf: {confidence})")
    else:
        logger.warning("⚠️ Supplier detection returned UNKNOWN")

    # --- Phase 2: Extraction ---
    logger.info(">>> Phase 2: Extracting Data...")
    processor = OrderProcessor()
    orders, cost_p2, raw_data_p2, _ = processor.process_file(
        file_path,
        mime_type=mime_type,
        email_context="Attached is the invoice.",
        supplier_instructions=supplier_instructions
    )
    
    # Save Phase 2 Raw Response
    p2_path = os.path.join(output_dir, "phase2_extraction.json")
    with open(p2_path, "w", encoding="utf-8") as f:
        json.dump(raw_data_p2, f, indent=4, ensure_ascii=False)
    logger.info(f"📄 Saved Phase 2 Raw Response: {p2_path}")
    
    total_usd = cost_p1 + cost_p2
    logger.info(f"Phase 2 Cost: ${cost_p2:.6f}")
    logger.info(f"💰 Total Pipeline Cost (USD): ${total_usd:.6f}")

    if orders:
        logger.info(f"✅ Extracted {len(orders)} orders.")
        
        for i, order in enumerate(orders):
            # Enrich with supplier info (simulating processor_fn logic)
            final_code = detected_code
            if final_code == "UNKNOWN" or confidence < 0.7:
                 matched = supplier_service.match_supplier(
                        global_id=order.supplier_global_id,
                        email=order.supplier_email,
                        phone=order.supplier_phone
                    )
                 if matched != "UNKNOWN":
                     final_code = matched
                     s_data = supplier_service.get_supplier(final_code)
                     supplier_name = s_data.get("name", "Unknown") if s_data else "Unknown"
                     logger.info(f"✅ Supplier Fallback Match: {supplier_name} ({final_code})")
            
            order.supplier_code = final_code
            order.supplier_name = supplier_name

            # Cost Assignment
            order.processing_cost = round(total_usd / len(orders), 6)
            order.processing_cost_ils = calculate_cost_ils(order.processing_cost)
            
            logger.info(f"--- Order {i+1} ---")
            logger.info(f"Invoice: {order.invoice_number}")
            logger.info(f"Cost: {order.processing_cost_ils:.3f} ₪ (${order.processing_cost:.6f})")

            # --- Generate Outputs ---
            safe_invoice = "".join([c if c.isalnum() else '_' for c in str(order.invoice_number)])
            
            # 1. JSON Dump
            json_path = os.path.join(output_dir, f"order_{safe_invoice}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(order.model_dump_json(indent=4))
            logger.info(f"📄 Saved JSON: {json_path}")

            # 2. Order Excel
            excel_path = os.path.join(output_dir, f"order_{safe_invoice}.xlsx")
            generate_excel_from_order(order, excel_path)
            logger.info(f"📊 Saved Excel: {excel_path}")

            # 3. New Items Excel (Simulated)
            order_barcodes = [str(item.barcode).strip() for item in order.line_items if item.barcode]
            new_barcodes = items_service.get_new_barcodes(order_barcodes)
            
            if new_barcodes:
                 new_items = filter_new_items_from_order(order, new_barcodes)
                 if new_items:
                     new_items_path = os.path.join(output_dir, f"new_items_{safe_invoice}.xlsx")
                     generate_new_items_excel(new_items, final_code, new_items_path)
                     logger.info(f"🆕 Saved New Items Excel: {new_items_path} ({len(new_items)} items)")
            else:
                logger.info("No new items detected.")

    else:
        logger.warning("❌ No orders extracted.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run tests/run_local_pipeline.py <path_to_invoice>")
    else:
        run_pipeline(sys.argv[1])
