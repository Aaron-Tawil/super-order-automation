import argparse
import json
import os
import shutil
import sys
import uuid
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
from src.shared.logger import get_logger
from src.shared.utils import get_mime_type, is_test_sender

logger = get_logger(__name__)


def run_pipeline(file_path: str, sender: str = "test@example.com"):
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    # Create Output Directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"local-{timestamp}-{uuid.uuid4().hex[:8]}"
    ctx = f"[run_id={run_id}] "
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = os.path.join(os.path.dirname(__file__), "output", f"{base_name}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    logger.info(f"{ctx}🚀 Starting Local Pipeline Test")
    logger.info(f"{ctx}📂 Input File: {file_path}")
    logger.info(f"{ctx}📂 Output Directory: {output_dir}")

    # Copy original file to output
    shutil.copy(file_path, output_dir)

    # Init Services
    init_client()

    # Check Currency Rate
    rate = get_usd_to_ils_rate()
    logger.info(f"{ctx}💱 Live USD to ILS Rate: {rate}")

    # Executing Unified Pipeline
    from src.core.pipeline import ExtractionPipeline

    pipeline = ExtractionPipeline()

    # Mock Email Metadata for local test
    mock_email_meta = {
        "sender": sender,
        "subject": f"Invoice for {os.path.basename(file_path)}",
        "body": "Please find attached.",
        "run_id": run_id,
    }

    # Always flag local test runs as 'TEST', regardless of the sender
    is_test_order = True
    logger.info(f"{ctx}📧 Mock Sender: {sender} (is_test={is_test_order} enforced)")

    mime_type = get_mime_type(file_path)
    logger.info(f"{ctx}Using MIME type: {mime_type}")

    result = pipeline.run_pipeline(file_path=file_path, mime_type=mime_type, email_metadata=mock_email_meta)

    # Save Raw Responses
    if result.raw_phase1_response:
        p1_path = os.path.join(output_dir, "phase1_supplier.json")
        with open(p1_path, "w", encoding="utf-8") as f:
            json.dump(result.raw_phase1_response, f, indent=4, ensure_ascii=False)
        logger.info(f"{ctx}📄 Saved Phase 1 Raw Response: {p1_path}")

    if result.raw_phase2_responses:
        for trial, response in result.raw_phase2_responses.items():
            p2_path = os.path.join(output_dir, f"phase2_extraction_trial_{trial}.json")
            with open(p2_path, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=4, ensure_ascii=False)

            error_status = " (INVALID/ERROR)" if "error" in response else ""
            logger.info(f"{ctx}📄 Saved Phase 2 Raw Response (Trial {trial}){error_status}: {p2_path}")

    if result.orders:
        for i, order in enumerate(result.orders):
            order.is_test = is_test_order

            logger.info(f"{ctx}--- Order {i + 1} ---")
            logger.info(f"{ctx}Invoice: {order.invoice_number}")
            logger.info(f"{ctx}Supplier ID: {order.supplier_code}")
            logger.info(f"{ctx}Cost: {order.processing_cost_ils:.3f} ₪ (${order.processing_cost:.6f})")
            if result.phase1_reasoning and i == 0:
                logger.info(f"{ctx}🔍 Phase 1 Reasoning: {result.phase1_reasoning}")
            if order.notes:
                logger.info(f"{ctx}📝 AI Notes: {order.notes}")
            if order.math_reasoning:
                logger.info(f"{ctx}💡 Math Reasoning: {order.math_reasoning}")
            if order.qty_reasoning:
                logger.info(f"{ctx}💡 Qty Reasoning: {order.qty_reasoning}")

            # --- Generate Outputs ---
            safe_invoice = "".join([c if c.isalnum() else "_" for c in str(order.invoice_number)])

            # 1. JSON Dump
            json_path = os.path.join(output_dir, f"order_{safe_invoice}.json")
            order_dict = json.loads(order.model_dump_json())
            order_dict["created_at"] = datetime.now().isoformat()  # mirrors Firestore metadata
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(order_dict, f, indent=4, ensure_ascii=False)
            logger.info(f"{ctx}📄 Saved JSON: {json_path}")

            # 2. Order Excel
            excel_path = os.path.join(output_dir, f"order_{safe_invoice}.xlsx")
            generate_excel_from_order(order, excel_path)
            logger.info(f"{ctx}📊 Saved Excel: {excel_path}")

            # 3. New Items Excel
            if result.new_items_data and i == 0:
                from src.shared.models import LineItem

                fake_new_items = [LineItem(**item) for item in result.new_items_data]
                new_items_path = os.path.join(output_dir, f"new_items_{safe_invoice}.xlsx")
                generate_new_items_excel(fake_new_items, order.supplier_code, new_items_path)
                logger.info(f"{ctx}🆕 Saved New Items Excel: {new_items_path} ({len(fake_new_items)} items)")

    else:
        logger.warning(f"{ctx}No orders extracted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run local extraction pipeline.")
    parser.add_argument("file", help="Path to local invoice file")
    parser.add_argument(
        "--sender", default="test@example.com", help="Mock sender email address (default: test@example.com)"
    )
    args = parser.parse_args()

    run_pipeline(args.file, args.sender)
    # yfinance spawns non-daemon threads for HTTP connection pooling that prevent
    # clean process exit without an explicit sys.exit().
    sys.exit(0)
