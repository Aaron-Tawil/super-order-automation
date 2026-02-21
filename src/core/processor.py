import os
from collections import defaultdict
from typing import List, Optional, Tuple

from src.core.exceptions import ExtractionError, ValidationError
from src.extraction import vertex_client
from src.shared.constants import MAX_RETRIES, VALIDATION_TOLERANCE, VAT_RATE
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder, LineItem, MultiOrderResponse
from src.shared.utils import get_mime_type

# Configure logger
logger = get_logger(__name__)


class OrderProcessor:
    """
    Handles the lifecycle of an order extraction:
    1. Orchestrates the LLM extraction via VertexClient.
    2. Applies business logic (post-processing, promotions).
    3. Validates the results.
    4. Managing retries if validation fails.
    """

    def process_file(
        self,
        file_path: str,
        mime_type: str = None,
        email_context: str = None,
        supplier_instructions: str = None,
    ) -> tuple[list[ExtractedOrder], float, dict, dict]:
        """
        Main entry point for processing a file.
        Returns:
            Tuple[List[ExtractedOrder], float, dict, dict]: (Extracted Orders, Total Cost USD, Raw Response, Response Metadata)
        """
        # Auto-detect MIME type if not provided
        if mime_type is None:
            mime_type = get_mime_type(file_path)
            logger.info(f"Auto-detected MIME type: {mime_type}")

        attempt = 0
        final_orders = []
        total_cost = 0.0
        all_raw_responses = {}
        final_metadata = {}

        while attempt <= MAX_RETRIES:
            trial_version = 1 if attempt == 0 else 2
            logger.warning(f"--- 📄 PIPELINE ATTEMPT {attempt + 1}/{MAX_RETRIES + 1} (TRIAL {trial_version}) ---")
            logger.warning(f"File: {os.path.basename(file_path)} | MIME: {mime_type}")

            # Step 1: Raw Extraction (LLM)
            try:
                orders, attempt_cost, metadata, raw_response = vertex_client.extract_invoice_data(
                    file_path=file_path,
                    mime_type=mime_type,
                    email_context=email_context,
                    supplier_instructions=supplier_instructions,
                    retry_count=attempt,
                )
                total_cost += attempt_cost
                all_raw_responses[trial_version] = raw_response
                final_metadata = metadata
            except Exception as e:
                logger.error(f"❌ Error during extraction (attempt {attempt}): {e}")
                if attempt < MAX_RETRIES:
                    attempt += 1
                    continue
                return [], total_cost, all_raw_responses, {}

            if not orders:
                logger.warning(f"⚠️ No orders returned from extraction (Attempt {attempt + 1}).")
                if attempt < MAX_RETRIES:
                    attempt += 1
                    continue
                return [], total_cost, all_raw_responses, final_metadata

            logger.info(f"✅ LLM returned {len(orders)} order(s). Applying post-processing (Trial {trial_version})...")

            validated_data = []
            critical_failure_found = False

            for i, order in enumerate(orders):
                # Step 2: Post-Processing logic
                logger.debug(f"Post-processing order {i+1}...")

                # 2a. Calculate net prices (if Trial 1)
                if trial_version == 1:
                    self._post_process_net_prices(order)

                # 2b. Apply promotions logic (e.g., 11+1 averaging) for BOTH trials
                self._post_process_promotions(order)

                # 2c. Filter zero quantity
                original_count = len(order.line_items)
                order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]
                filtered_count = len(order.line_items)

                if original_count != filtered_count:
                    logger.info(f"Filtered out {original_count - filtered_count} lines with 0 quantity.")

                # Step 3: Validation
                is_valid_total, calc_total, diff_total = self._validate_totals(order, trial_version)

                if not is_valid_total:
                    reason_msg = f" (Reason: {order.math_reasoning})" if order.math_reasoning else ""
                    msg = (
                        f"Validation Failed: Document Total ({order.document_total_with_vat}) "
                        f"!= Calculated Total ({calc_total:.2f}). Diff: {diff_total:.2f}{reason_msg}"
                    )
                    logger.warning(f"❌ {msg}")
                    order.warnings.append(msg)
                    critical_failure_found = True
                else:
                    logger.warning(f"✅ Validation Passed for Order {i+1}! Diff: {diff_total:.2f}")

                # Quantity Validation
                is_valid_qty, calc_qty, diff_qty = self._validate_quantity(order, trial_version)
                if not is_valid_qty:
                    reason_msg = f" (Reason: {order.qty_reasoning})" if order.qty_reasoning else ""
                    msg = (
                        f"Quantity Validation Failed: Document Qty ({order.document_total_quantity}) "
                        f"!= Calculated ({calc_qty}). Diff: {diff_qty}{reason_msg}"
                    )
                    logger.warning(f"⚠️ {msg}")
                    order.warnings.append(msg)
                else:
                    logger.info(f"✅ Quantity Validation Passed! Diff: {diff_qty}")

                validated_data.append(order)

            # Step 4: Retry Decision
            if critical_failure_found and attempt < MAX_RETRIES:
                logger.warning(
                    f"🔄 CRITICAL VALIDATION FAILED. Switching to Trial 2 logic... (Next: Attempt {attempt + 1})"
                )
                attempt += 1
                continue

            # If we get here, either success or max retries reached
            final_orders = validated_data
            logger.warning(f"✨ Extraction Phase Finished. Total Orders: {len(final_orders)}")
            break

        if final_metadata:
            for order in final_orders:
                order.ai_metadata = final_metadata

        return final_orders, total_cost, all_raw_responses, final_metadata

    def _calculate_final_net_price(
        self,
        raw_unit_price: float,
        discount_pct: float,
        global_discount_pct: float,
        vat_status: str,
    ) -> float:
        """
        Calculate final_net_price from raw extracted values.
        """
        price = raw_unit_price or 0.0

        # 1. Apply line-level discount
        if discount_pct:
            price *= 1 - discount_pct / 100

        # 2. Apply global discount
        if global_discount_pct:
            price *= 1 - global_discount_pct / 100

        # 3. Remove VAT if prices are VAT-inclusive
        if vat_status == "INCLUDED":
            price /= 1 + VAT_RATE

        return round(price, 4)

    def _post_process_net_prices(self, order: ExtractedOrder):
        """
        Calculate final_net_price for each line item (Trial 1).
        If there's a total_invoice_discount_amount, distribute it proportionally.
        """
        global_discount_pct = order.global_discount_percentage or 0.0

        # Pass 1: Calculate base net price for all items
        for item in order.line_items:
            item.final_net_price = self._calculate_final_net_price(
                item.raw_unit_price,
                item.discount_percentage,
                global_discount_pct,
                item.vat_status.value,
            )

        # Pass 2: Distribute lump-sum discount proportionally ONLY if no percentage was provided
        # (This prevents double-dipping since percentage and amount usually represent the same discount)
        discount_amount = order.total_invoice_discount_amount or 0.0
        if discount_amount > 0 and global_discount_pct == 0.0:
            # Calculate total raw value to find the ratio
            total_net_value = sum((item.final_net_price or 0.0) * (item.quantity or 0.0) for item in order.line_items)
            
            if total_net_value > 0:
                # E.g. 50 ILS discount on 500 ILS total = 10% reduction (ratio = 0.90)
                discount_ratio = 1.0 - (discount_amount / total_net_value)
                for item in order.line_items:
                    item.final_net_price = round((item.final_net_price or 0.0) * discount_ratio, 4)

    def _post_process_promotions(self, order: ExtractedOrder):
        """
        Handles split lines for "X+Y derived" promotions (e.g. 11+1).
        """
        if not order.line_items:
            return

        grouped_items = defaultdict(list)

        # Group items by barcode
        for item in order.line_items:
            # Use a fallback key if barcode is missing
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

            logger.info(
                f"Applying avg price {avg_net_price:.2f} to {len(items)} lines for {barcode} (Total Qty: {total_qty})"
            )

            # Apply strict average to all lines
            for item in items:
                item.final_net_price = avg_net_price

            new_line_items.extend(items)

        order.line_items = new_line_items

    def _validate_totals(self, order: ExtractedOrder, trial_version: int) -> tuple[bool, float, float]:
        """
        Validates that the sum of line items matches the document total.
        Supports multiple common invoice math patterns for Trial 1 (Raw).
        For Trial 2 (LLM Calc), evaluates exactly one simple math formula.
        """
        if order.document_total_with_vat is None:
            return True, 0.0, 0.0

        # 1. Normalize VAT Rate
        vat_factor = 1 + VAT_RATE
        
        # 2. Calculate base components
        total_line_net = sum((item.final_net_price or 0.0) * (item.quantity or 0.0) for item in order.line_items)
        
        # Trial 2 Validation (LLM calculated the final net price itself, just verifying the pure sum)
        if trial_version == 2:
            # We trust the LLM's own self-verification flag for math via Sandbox execution
            is_valid = order.is_math_valid
            
            # If the LLM didn't return a flag (e.g. failure to adhere to schema), fallback to basic math check
            if is_valid is None:
                calc = total_line_net * vat_factor
                diff = abs(calc - order.document_total_with_vat)
                is_valid = diff <= VALIDATION_TOLERANCE
                return is_valid, calc, diff

            # If LLM said it's invalid, calculate the diff for the warning message
            calc = total_line_net * vat_factor
            diff = abs(calc - order.document_total_with_vat)
            return is_valid, calc, diff

        # Trial 1 Validation
        # The line items already had ALL global and lump sum discounts mathematically baked into them.
        # We only need to multiply by the vat_factor.
        calculated_total = total_line_net * vat_factor

        diff = abs(calculated_total - order.document_total_with_vat)
        is_valid = diff <= VALIDATION_TOLERANCE

        if not is_valid:
            logger.info(
                f"DEBUG Validation (Trial 1): Net Sum={total_line_net:.2f}, "
                f"VAT Factor={vat_factor:.2f}"
            )
            logger.info(
                f"DEBUG Validation (Trial 1): Document says {order.document_total_with_vat}, "
                f"calc was {calculated_total:.2f}"
            )

        return is_valid, calculated_total, diff

    def _validate_quantity(self, order: ExtractedOrder, trial_version: int) -> tuple[bool, float, float]:
        """
        Validates that the sum of line item quantities matches the document total quantity.
        Returns: Tuple[is_valid, calculated_total, difference]
        """
        if order.document_total_quantity is None:
            return True, 0.0, 0.0

        calculated_quantity = sum((item.quantity or 0) for item in order.line_items)

        # Trial 2 Validation (LLM verified quantity)
        if trial_version == 2:
            is_valid = order.is_qty_valid
            
            if is_valid is None:
                diff = abs(calculated_quantity - order.document_total_quantity)
                is_valid = diff <= 0.1
                return is_valid, calculated_quantity, diff
                
            diff = abs(calculated_quantity - order.document_total_quantity)
            return is_valid, calculated_quantity, diff

        diff = abs(calculated_quantity - order.document_total_quantity)

        # Use a small tolerance for float comparison
        is_valid = diff <= 0.1

        return is_valid, calculated_quantity, diff
