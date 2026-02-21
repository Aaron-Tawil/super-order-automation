from typing import Optional

from pydantic import BaseModel, Field

from src.core.processor import OrderProcessor
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.export.new_items_generator import filter_new_items_from_order
from src.extraction.local_detector import LocalSupplierDetector
from src.extraction.vertex_client import detect_supplier
from src.shared.ai_cost import calculate_cost_ils
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder

logger = get_logger(__name__)

class PipelineResult(BaseModel):
    """Standardized output from the ExtractionPipeline."""
    orders: list[ExtractedOrder] = Field(default_factory=list)
    supplier_code: str = "UNKNOWN"
    supplier_name: str = "Unknown"
    confidence: float = 0.0
    detection_method: str = "none"
    phase1_reasoning: str | None = None
    
    total_cost_usd: float = 0.0
    total_cost_ils: float = 0.0
    
    new_items_added: int = 0
    added_barcodes: list[str] = Field(default_factory=list)
    new_items_data: list[dict] = Field(default_factory=list) # For Dashboard Display
    
    raw_phase1_response: dict | None = None
    raw_phase2_responses: dict = Field(default_factory=dict)

class ExtractionPipeline:
    """
    Central orchestrator for extracting order data from an invoice.
    Combines Local Detection, AI Detection, Extraction, and Item Registration.
    """
    
    def __init__(self):
        self.supplier_service = SupplierService()
        self.items_service = ItemsService()
        self.local_detector = LocalSupplierDetector()
        self.processor = OrderProcessor()

    def run_pipeline(
        self,
        file_path: str,
        mime_type: str,
        email_metadata: dict | None = None,
        force_supplier_instructions: str | None = None
    ) -> PipelineResult:
        """
        Executes the full extraction pipeline flow.
        """
        result = PipelineResult()
        
        # --- PHASE 0: Local Supplier Detection ---
        logger.info(">>> PHASE 0: Local Supplier Detection...")
        detected_code, confidence, detection_method = self.local_detector.detect_supplier(
            file_path=file_path,
            mime_type=mime_type,
            email_metadata=email_metadata
        )
        
        phase1_cost = 0.0
        detected_email = None
        detected_id = None
        email_context = email_metadata.get("body", "") if email_metadata else ""
        
        if detected_code != "UNKNOWN":
             logger.info(f"✅ Supplier Locally Detected via {detection_method}: {detected_code} (Conf: {confidence})")
             result.supplier_code = detected_code
             result.confidence = confidence
             result.detection_method = detection_method
        else:
            # --- PHASE 1: AI Supplier Detection ---
            logger.info("⚠️ Local detection failed. Proceeding to Vertex AI...")
            logger.info(">>> PHASE 1: Supplier Detection (Vertex AI)...")
            
            detected_code, confidence, phase1_cost, reasoning, raw_data_p1, detected_email, detected_id = detect_supplier(
                email_body=email_context,
                invoice_file_path=file_path,
                invoice_mime_type=mime_type
            )
            logger.info(f"Phase 1 Cost: ${phase1_cost:.6f}")
            
            result.supplier_code = detected_code
            result.confidence = confidence
            result.detection_method = "vertex_ai"
            result.raw_phase1_response = raw_data_p1
            result.phase1_reasoning = reasoning
        
        
        # --- Auto-Learning: Add detected email & ID to supplier ---
        if result.supplier_code != "UNKNOWN":
            # 1. Email
            if detected_email:
                detected_email = detected_email.strip().lower()
                if "@" in detected_email and not self.local_detector._is_blacklisted_email(detected_email):
                   logger.info(f"🧠 Auto-Learning: Attempting to link {detected_email} to {result.supplier_code}")
                   try:
                       success, was_added = self.supplier_service.add_email_to_supplier(result.supplier_code, detected_email)
                       if success and was_added:
                           logger.info(f"🎉 Auto-Learned: {detected_email} is now linked to {result.supplier_code}")
                       elif success and not was_added:
                           logger.info(f"Email {detected_email} already linked to {result.supplier_code}")
                   except Exception as e:
                       logger.error(f"Auto-learning email failed: {e}")

            # 2. Global ID (Business ID)
            if detected_id:
                logger.info(f"🧠 Auto-Learning: Attempting to link ID {detected_id} to {result.supplier_code}")
                try:
                     success, was_added = self.supplier_service.update_missing_global_id(result.supplier_code, detected_id)
                     if success and was_added:
                         logger.info(f"🎉 Auto-Learned: ID {detected_id} is now linked to {result.supplier_code}")
                     elif success and not was_added:
                         logger.info(f"ID {detected_id} already linked to {result.supplier_code}")
                except Exception as e:
                    logger.error(f"Auto-learning ID failed: {e}")
        # -----------------------------------------------------

        supplier_instructions = None
        if force_supplier_instructions is not None:
             supplier_instructions = force_supplier_instructions
        elif result.supplier_code != "UNKNOWN":
            s_data = self.supplier_service.get_supplier(result.supplier_code)
            if s_data:
                result.supplier_name = s_data.get("name", "Unknown")
                supplier_instructions = s_data.get("special_instructions")
                logger.info(f"✅ Supplier Identified: {result.supplier_name} ({result.supplier_code})")
        else:
            logger.warning("⚠️ Supplier detection returned UNKNOWN.")

        # --- PHASE 2: Extraction & Post-Processing ---
        logger.info(">>> PHASE 2: Extraction & Post-Processing...")
        orders, phase2_cost, all_raw_responses, _ = self.processor.process_file(
            file_path, 
            mime_type=mime_type, 
            email_context=email_context,
            supplier_instructions=supplier_instructions
        )
        
        result.raw_phase2_responses = all_raw_responses
        result.total_cost_usd = phase1_cost + phase2_cost
        result.total_cost_ils = calculate_cost_ils(result.total_cost_usd)
        
        logger.info(f"Phase 2 Cost: ${phase2_cost:.6f} | Total Pipeline Cost: ${result.total_cost_usd:.6f}")

        if not orders:
            logger.warning("❌ No orders extracted.")
            return result

        logger.info(f"✅ Successfully extracted {len(orders)} order(s).")
        result.orders = orders

        # Final pass over extracted orders: Fallback Matching, Cost Splitting, and new item detection
        added_barcodes = []
        new_items_display_data = []
        
        for i, order in enumerate(result.orders):
            # 1. Fallback supplier matching (if Phase 0 and Phase 1 failed or had low confidence)
            if result.supplier_code == "UNKNOWN" or result.confidence < 0.7:
                matched = self.supplier_service.match_supplier(
                    global_id=order.supplier_global_id or detected_id,
                    email=order.supplier_email or detected_email,
                    phone=order.supplier_phone
                )
                if matched != "UNKNOWN":
                    result.supplier_code = matched
                    s_data = self.supplier_service.get_supplier(result.supplier_code)
                    result.supplier_name = s_data.get("name", "Unknown") if s_data else "Unknown"
                    result.detection_method = "extraction_fallback"
                    logger.info(f"✅ Supplier Fallback Match: {result.supplier_name} ({result.supplier_code})")

            # Update Order Object Supplier
            order.supplier_code = result.supplier_code
            order.supplier_name = result.supplier_name
            
            # 2. Pro-Rate Cost
            order.processing_cost = round(result.total_cost_usd / len(result.orders), 6)
            order.processing_cost_ils = calculate_cost_ils(order.processing_cost)
            
            # 3. New Items Detection
            order_barcodes = [str(item.barcode).strip() for item in order.line_items if item.barcode]
            # Valid barcodes strictly > length 10 are checked
            valid_barcodes = [b for b in order_barcodes if len(b) >= 11]
            
            if valid_barcodes:
                 new_barcodes = self.items_service.get_new_barcodes(valid_barcodes)
                 if new_barcodes:
                     # Filter full item objects for creation
                     new_items = filter_new_items_from_order(order, new_barcodes)
                     
                     items_to_add = []
                     seen = set()
                     for item in new_items:
                         if item.barcode not in seen:
                             # Default item_code = barcode
                             items_to_add.append({
                                 "barcode": item.barcode,
                                 "name": item.description,
                                 "item_code": item.barcode
                             })
                             
                             new_items_display_data.append({
                                 "barcode": str(item.barcode),
                                 "description": item.description,
                                 "final_net_price": item.final_net_price or 0.0
                             })
                             seen.add(item.barcode)
                     
                     if items_to_add:
                         try:
                             added_count = self.items_service.add_new_items_batch(items_to_add)
                             result.new_items_added += added_count
                             added_barcodes.extend([i["barcode"] for i in items_to_add])
                             logger.info(f"✅ Auto-added {added_count} new items to DB.")
                         except Exception as e:
                             logger.error(f"Failed to save new items: {e}")

        result.added_barcodes = added_barcodes
        result.new_items_data = new_items_display_data
        
        return result
