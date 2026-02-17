import os
from collections import defaultdict
from typing import List, Optional, Tuple

from src.core.exceptions import ExtractionError, ValidationError
from src.core.models import ExtractedOrder, LineItem, MultiOrderResponse
from src.extraction import vertex_client
from src.shared.constants import MAX_RETRIES, VALIDATION_TOLERANCE, VAT_RATE
from src.shared.logger import get_logger

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
    ) -> list[ExtractedOrder]:
        """
        Main entry point for processing a file.
        """
        # Auto-detect MIME type if not provided
        if mime_type is None:
            ext = os.path.splitext(file_path.lower())[1]
            mime_types = {
                ".pdf": "application/pdf",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".xls": "application/vnd.ms-excel",
            }
            mime_type = mime_types.get(ext, "application/pdf")
            logger.info(f"Auto-detected MIME type: {mime_type}")

        attempt = 0
        final_orders = []

        while attempt <= MAX_RETRIES:
            logger.warning(f"--- 📄 PIPELINE ATTEMPT {attempt + 1}/{MAX_RETRIES + 1} ---")
            logger.warning(f"File: {os.path.basename(file_path)} | MIME: {mime_type}")

            # Step 1: Raw Extraction (LLM)
            try:
                orders = vertex_client.extract_invoice_data(
                    file_path=file_path,
                    mime_type=mime_type,
                    email_context=email_context,
                    supplier_instructions=supplier_instructions,
                    retry_count=attempt,
                )
            except Exception as e:
                logger.error(f"❌ Error during extraction (attempt {attempt}): {e}")
                if attempt < MAX_RETRIES:
                    attempt += 1
                    continue
                return []

            if not orders:
                logger.warning("⚠️ No orders returned from extraction.")
                return []

            logger.info(f"✅ LLM returned {len(orders)} order(s). Applying post-processing...")

            validated_data = []
            critical_failure_found = False

            for i, order in enumerate(orders):
                # Step 2: Post-Processing logic
                logger.debug(f"Post-processing order {i+1}...")

                # 2a. Calculate net prices (if v2 prompt used and they are empty)
                if attempt == 0:
                    self._post_process_net_prices(order)

                # 2b. Start Promotions logic (11+1 etc)
                self._post_process_promotions(order)

                # 2c. Filter zero quantity
                original_count = len(order.line_items)
                order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]
                filtered_count = len(order.line_items)

                if original_count != filtered_count:
                    logger.info(f"Filtered out {original_count - filtered_count} lines with 0 quantity.")

                # Step 3: Validation
                is_valid_total, calc_total, diff_total = self._validate_totals(order)

                if not is_valid_total:
                    msg = (
                        f"Validation Failed: Document Total ({order.document_total_with_vat}) "
                        f"!= Calculated Total ({calc_total:.2f}). Diff: {diff_total:.2f}"
                    )
                    logger.warning(f"❌ {msg}")
                    order.warnings.append(msg)
                    critical_failure_found = True
                else:
                    logger.warning(f"✅ Validation Passed for Order {i+1}! Diff: {diff_total:.2f}")

                # Quantity Validation
                is_valid_qty, calc_qty, diff_qty = self._validate_quantity(order)
                if not is_valid_qty:
                    msg = (
                        f"Quantity Validation Failed: Document Qty ({order.document_total_quantity}) "
                        f"!= Calculated ({calc_qty}). Diff: {diff_qty}"
                    )
                    logger.warning(f"⚠️ {msg}")
                    order.warnings.append(msg)
                else:
                    logger.info(f"✅ Quantity Validation Passed! Diff: {diff_qty}")

                validated_data.append(order)

            # Step 4: Retry Decision
            if critical_failure_found and attempt < MAX_RETRIES:
                logger.warning(
                    f"🔄 CRITICAL VALIDATION FAILED. Retrying with higher precision model... (Next: Attempt {attempt + 2})"
                )
                attempt += 1
                continue

            # If we get here, either success or max retries reached
            final_orders = validated_data
            logger.warning(f"✨ Extraction Phase Finished. Total Orders: {len(final_orders)}")
            break

        return final_orders

    def _calculate_final_net_price(
        self,
        raw_unit_price: float,
        discount_pct: float,
        global_discount_pct: float,
        vat_status: str,
        vat_rate: float,
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
        # CRITICAL EXCEPTION: If global_discount_pct is ~15.25%, it IS the VAT removal.
        is_vat_removal_discount = 15.1 <= (global_discount_pct or 0) <= 15.5
        
        if vat_status == "INCLUDED" and not is_vat_removal_discount:
            price /= 1 + vat_rate / 100

        return round(price, 4)

    def _post_process_net_prices(self, order: ExtractedOrder):
        """
        Calculate final_net_price for each line item if missing.
        """
        global_discount_pct = order.global_discount_percentage or 0.0
        vat_rate = order.vat_rate or (VAT_RATE * 100)

        for item in order.line_items:
            # Only calculate if the LLM left it null/zero (v2 behavior)
            if not item.final_net_price or item.final_net_price == 0.0:
                item.final_net_price = self._calculate_final_net_price(
                    item.raw_unit_price,
                    item.discount_percentage,
                    global_discount_pct,
                    item.vat_status.value,
                    vat_rate,
                )

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

    def _validate_totals(self, order: ExtractedOrder) -> tuple[bool, float, float]:
        """
        Validates that the sum of line items matches the document total.
        Supports multiple common invoice math patterns.
        """
        if order.document_total_with_vat is None:
            return True, 0.0, 0.0

        # 1. Normalize VAT Rate
        raw_vat = order.vat_rate if order.vat_rate is not None else (VAT_RATE * 100)
        if 0 < raw_vat < 1.0: # Handle cases where AI returns 0.18 instead of 18
            raw_vat *= 100
        vat_factor = 1 + (raw_vat / 100)
        
        # 2. Calculate base components
        total_line_net = sum((item.final_net_price or 0.0) * (item.quantity or 0.0) for item in order.line_items)
        
        # 3. Try different logical combinations to match document_total_with_vat
        # (Accounting formats vary on whether discounts apply before or after VAT)
        discount = order.total_invoice_discount_amount or 0.0
        
        possibilities = {
            "Standard (Net -> VAT -> -Discount)": (total_line_net * vat_factor) - discount,
            "Discounted (Net -> -Discount -> VAT)": (total_line_net - discount) * vat_factor,
            "Implicit (Already discounted lines -> VAT)": total_line_net * vat_factor,
            "Direct (Net sum matches Gross - AI Error)": total_line_net
        }

        best_diff = float('inf')
        best_calc = 0.0
        
        for label, calc in possibilities.items():
            diff = abs(calc - order.document_total_with_vat)
            if diff < best_diff:
                best_diff = diff
                best_calc = calc

        is_valid = best_diff <= VALIDATION_TOLERANCE

        if not is_valid:
            logger.info(f"DEBUG Validation: Net Sum={total_line_net:.2f}, VAT Factor={vat_factor:.2f}, Discount={discount:.2f}")
            logger.info(f"DEBUG Validation: Document says {order.document_total_with_vat}, closest calc was {best_calc:.2f}")

        return is_valid, best_calc, best_diff

    def _validate_quantity(self, order: ExtractedOrder) -> tuple[bool, float, float]:
        """
        Validates that the sum of line item quantities matches the document total quantity.
        Returns: Tuple[is_valid, calculated_total, difference]
        """
        if order.document_total_quantity is None:
            return True, 0.0, 0.0

        calculated_quantity = sum((item.quantity or 0) for item in order.line_items)
        diff = abs(calculated_quantity - order.document_total_quantity)

        # Use a small tolerance for float comparison
        is_valid = diff <= 0.1

        return is_valid, calculated_quantity, diff
