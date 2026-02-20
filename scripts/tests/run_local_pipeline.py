
import json
import logging
import os
import shutil
import sys
from datetime import datetime

# Add project root to path (scripts/tests/ -> scripts/ -> /)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

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
    
    # Check Currency Rate
    rate = get_usd_to_ils_rate()
    logger.info(f"💱 Live USD to ILS Rate: {rate}")

    # Executing Unified Pipeline
    from src.core.pipeline import ExtractionPipeline
    pipeline = ExtractionPipeline()
    
    # Mock Email Metadata for local test
    mock_email_meta = {
        "sender": "example@supplier.com", 
        "subject": f"Invoice for {os.path.basename(file_path)}",
        "body": "Please find attached."
    }
    
    mime_type = "application/pdf" if file_path.lower().endswith(".pdf") else "application/octet-stream"
    if file_path.lower().endswith(".xlsx"):
         mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    result = pipeline.run_pipeline(
        file_path=file_path,
        mime_type=mime_type,
        email_metadata=mock_email_meta
    )
    
    # Save Raw Responses
    if result.raw_phase1_response:
        p1_path = os.path.join(output_dir, "phase1_supplier.json")
        with open(p1_path, "w", encoding="utf-8") as f:
            json.dump(result.raw_phase1_response, f, indent=4, ensure_ascii=False)
        logger.info(f"📄 Saved Phase 1 Raw Response: {p1_path}")

    if result.raw_phase2_responses:
        for trial, response in result.raw_phase2_responses.items():
            p2_path = os.path.join(output_dir, f"phase2_extraction_trial_{trial}.json")
            with open(p2_path, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=4, ensure_ascii=False)
            logger.info(f"📄 Saved Phase 2 Raw Response (Trial {trial}): {p2_path}")

    if result.orders:
        for i, order in enumerate(result.orders):
            logger.info(f"--- Order {i+1} ---")
            logger.info(f"Invoice: {order.invoice_number}")
            logger.info(f"Supplier ID: {order.supplier_code}")
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

            # 3. New Items Excel
            if result.new_items_data and i == 0:
                 from src.shared.models import LineItem
                 fake_new_items = [LineItem(**item) for item in result.new_items_data]
                 new_items_path = os.path.join(output_dir, f"new_items_{safe_invoice}.xlsx")
                 generate_new_items_excel(fake_new_items, order.supplier_code, new_items_path)
                 logger.info(f"🆕 Saved New Items Excel: {new_items_path} ({len(fake_new_items)} items)")

    else:
        logger.warning("❌ No orders extracted.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run scripts/tests/run_local_pipeline.py <path_to_invoice>")
    else:
        run_pipeline(sys.argv[1])
