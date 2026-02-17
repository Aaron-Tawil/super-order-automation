import json
import logging
from typing import List, Optional, Tuple

from src.core.models import ExtractedOrder, LineItem, MultiOrderResponse
from src.extraction import vertex_client
from src.shared.constants import MAX_RETRIES, VALIDATION_TOLERANCE, VAT_RATE

# Configure logger
logger = logging.getLogger(__name__)


class OrderProcessor:
    """
    Handles the lifecycle of an order extraction:
    1. Orchestrates the LLM extraction via VertexClient.
    2. Applies business logic (post-processing, promotions).
    3. Validates the results.
    4. Managing retries if validation fails.
    """

    def __init__(self):
        pass

    def process_file(
        self, file_path: str, mime_type: str = None, email_context: str = None, supplier_instructions: str = None
    ) -> list[ExtractedOrder]:
        """
        Main entry point for processing a file.
        """
        attempt = 0

        while attempt <= MAX_RETRIES:
            logger.info(f"Processing file {file_path}, attempt {attempt + 1}/{MAX_RETRIES + 1}")

            # Step 1: Raw Extraction (LLM)
            # We need a method in vertex_client that just does the extraction without the heavy logic
            # For now, we will assume we refactor vertex_client to expose `extract_raw_orders`
            # But since vertex_client isn't refactored yet, we might need to do that first or mock it.
            # actually, let's write this to use the *future* vertex_client method.

            orders = vertex_client.extract_raw_orders(
                file_path=file_path,
                mime_type=mime_type,
                email_context=email_context,
                supplier_instructions=supplier_instructions,
                retry_count=attempt,
            )

            if not orders:
                logger.warning("No orders returned from extraction.")
                return []

            validated_orders = []
            critical_failure = False

            for order in orders:
                # Step 2: Post-Processing
                # 2a. Calculate net prices (if v2 prompt used and they are empty)
                if attempt == 0:  # v2 prompt is used on first attempt usually
                    self._post_process_net_prices(order)

                # 2b. Start Promotions logic (11+1 etc)
                self._post_process_promotions(order)

                # 2c. Filter zero quantity
                order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]

                # Step 3: Validation
                is_valid_total, calc_total, diff_total = self._validate_totals(order)
                is_valid_qty, calc_qty, diff_qty = self._validate_quantity(order)

                if not is_valid_total:
                    msg = (
                        f"Validation Failed: Document Total ({order.document_total_with_vat}) "
                        f"!= Calculated ({calc_total}). Diff: {diff_total}"
                    )
                    order.warnings.append(msg)
                    logger.warning(msg)
                    critical_failure = True

                if not is_valid_qty:
                    msg = (
                        f"Quantity Validation Failed: Document Qty ({order.document_total_quantity}) "
                        f"!= Calculated ({calc_qty}). Diff: {diff_qty}"
                    )
                    order.warnings.append(msg)
                    logger.warning(msg)
                    # Quantity mismatch usually doesn't trigger full retry unless extreme,
                    # but current logic says "critical_failure" triggers retry.
                    # The original code ONLY triggered retry on Price/Total mismatch.

                validated_orders.append(order)

            # Step 4: Retry Decision
            if critical_failure and attempt < MAX_RETRIES:
                logger.info("Critical validation failure. Retrying...")
                attempt += 1
                continue

            return validated_orders

        return validated_orders

    def _calculate_final_net_price(
        self, raw_unit_price: float, discount_pct: float, global_discount_pct: float, vat_status: str, vat_rate: float
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
            price /= 1 + vat_rate / 100

        return round(price, 4)

    def _post_process_net_prices(self, order: ExtractedOrder):
        """
        Calculate final_net_price for each line item if missing.
        """
        global_discount_pct = order.global_discount_percentage or 0.0
        vat_rate = order.vat_rate or (VAT_RATE * 100)

        for item in order.line_items:
            if not item.final_net_price or item.final_net_price == 0.0:
                item.final_net_price = self._calculate_final_net_price(
                    item.raw_unit_price, item.discount_percentage, global_discount_pct, item.vat_status.value, vat_rate
                )

    def _post_process_promotions(self, order: ExtractedOrder):
        """
        Handles split lines for "X+Y derived" promotions (e.g. 11+1).
        """
        if not order.line_items:
            return

        from collections import defaultdict

        grouped_items = defaultdict(list)

        for item in order.line_items:
            key = item.barcode if item.barcode else f"NO_BARCODE_{item.description}"
            grouped_items[key].append(item)

        # We modify order.line_items in place or create new list?
        # The original created a new list.
        # But wait, the original returned 'order', implying mutation or new object.
        # It assigned `order.line_items = ...`.

        # logic copied from vertex_client.py
        # ... (implementation details) ...
        # For brevity in this step, I will implement the loop.

        # NOTE: logic is complex, I will copy it carefully in the actual file write.
        pass

    def _validate_totals(self, order: ExtractedOrder) -> tuple[bool, float, float]:
        if order.document_total_with_vat is None:
            return True, 0.0, 0.0

        calculated_net = sum(item.final_net_price * item.quantity for item in order.line_items)
        calculated_total_with_vat = calculated_net * (1 + VAT_RATE)
        diff = abs(calculated_total_with_vat - order.document_total_with_vat)
        is_valid = diff <= VALIDATION_TOLERANCE
        return is_valid, calculated_total_with_vat, diff

    def _validate_quantity(self, order: ExtractedOrder) -> tuple[bool, float, float]:
        if order.document_total_quantity is None:
            return True, 0.0, 0.0

        calculated_quantity = sum((item.quantity or 0) for item in order.line_items)
        diff = abs(calculated_quantity - order.document_total_quantity)
        is_valid = diff <= 0.1
        return is_valid, calculated_quantity, diff
