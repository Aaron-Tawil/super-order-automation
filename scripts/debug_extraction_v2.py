"""
Full-cycle test for v2 prompt extraction.
Runs the complete pipeline:
  Phase 1: Supplier detection
  Phase 2: Invoice extraction with v2 prompt + supplier instructions
  Post-processing: Calculate final_net_price, handle 11+1 promotions, validate totals
"""

import json
import os
import subprocess
import sys
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from google.genai import types

from src.extraction.prompts import get_invoice_extraction_prompt
from src.extraction.schemas import pdf_response_schema
from src.extraction.vertex_client import (
    detect_supplier,
    generate_content_safe,
    init_client,
    load_suppliers_csv,
    read_excel_safe,
)
from src.shared.constants import VALIDATION_TOLERANCE, VAT_RATE
from src.shared.models import ExtractedOrder, MultiOrderResponse

# ──────────────────────────────────────────────
#  POST-PROCESSING FUNCTIONS (v2 Python-side)
# ──────────────────────────────────────────────


def calculate_final_net_price(raw_unit_price, discount_pct, global_discount_pct, vat_status, vat_rate):
    """Calculate final_net_price from raw extracted values (Python-side)."""
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


def post_process_promotions(order: ExtractedOrder) -> ExtractedOrder:
    """
    Handle 11+1 style promotions: group by barcode, calculate weighted avg price.
    Same logic as vertex_client.post_process_promotions.
    """
    if not order.line_items:
        return order

    grouped_items = defaultdict(list)

    for item in order.line_items:
        key = item.barcode if item.barcode else f"NO_BARCODE_{item.description}"
        grouped_items[key].append(item)

    new_line_items = []

    for barcode, items in grouped_items.items():
        if len(items) == 1:
            new_line_items.extend(items)
            continue

        total_qty = sum(item.quantity for item in items)
        total_cost = sum(item.quantity * item.final_net_price for item in items)

        if total_qty == 0:
            new_line_items.extend(items)
            continue

        avg_net_price = total_cost / total_qty

        print(
            f"  🔄 Promotion detected: avg price {avg_net_price:.2f} for {len(items)} lines of {barcode} (Total Qty: {total_qty})"
        )

        for item in items:
            updated_item = item.model_copy()
            updated_item.final_net_price = round(avg_net_price, 4)
            new_line_items.append(updated_item)

    order.line_items = new_line_items
    return order


def post_process_order(order: ExtractedOrder) -> ExtractedOrder:
    """
    Full post-processing pipeline for a v2-extracted order:
    1. Calculate final_net_price for each line item
    2. Handle 11+1 promotions
    3. Filter zero-quantity lines
    """
    global_discount_pct = order.global_discount_percentage or 0.0
    vat_rate = order.vat_rate or (VAT_RATE * 100)

    # Step 1: Calculate final_net_price for each line
    for item in order.line_items:
        # Only calculate if the LLM left it null/zero (v2 behavior)
        if not item.final_net_price or item.final_net_price == 0.0:
            item.final_net_price = calculate_final_net_price(
                item.raw_unit_price, item.discount_percentage, global_discount_pct, item.vat_status.value, vat_rate
            )

    # Step 2: Handle 11+1 promotions
    order = post_process_promotions(order)

    # Step 3: Filter zero-quantity lines
    original_count = len(order.line_items)
    order.line_items = [item for item in order.line_items if (item.quantity or 0) > 0]
    filtered_count = len(order.line_items)
    if original_count != filtered_count:
        print(f"  Filtered out {original_count - filtered_count} zero-qty lines.")

    return order


def validate_order(order: ExtractedOrder) -> list:
    """Validate order totals and quantities. Returns list of warnings."""
    warnings = []
    vat_rate_decimal = (order.vat_rate or (VAT_RATE * 100)) / 100

    # Total validation
    if order.document_total_with_vat is not None:
        calculated_net = sum(item.final_net_price * item.quantity for item in order.line_items)
        calculated_total = calculated_net * (1 + vat_rate_decimal)
        diff = abs(calculated_total - order.document_total_with_vat)

        if diff <= VALIDATION_TOLERANCE:
            print(f"  ✅ Total validation PASSED (diff: {diff:.2f})")
        else:
            msg = f"Total mismatch: calculated={calculated_total:.2f}, document={order.document_total_with_vat:.2f}, diff={diff:.2f}"
            print(f"  ❌ {msg}")
            warnings.append(msg)

    # Quantity validation
    if order.document_total_quantity is not None:
        calculated_qty = sum((item.quantity or 0) for item in order.line_items)
        diff_qty = abs(calculated_qty - order.document_total_quantity)

        if diff_qty <= 0.1:
            print(f"  ✅ Quantity validation PASSED (diff: {diff_qty:.1f})")
        else:
            msg = f"Quantity mismatch: calculated={calculated_qty}, document={order.document_total_quantity}, diff={diff_qty}"
            print(f"  ⚠️  {msg}")
            warnings.append(msg)

    return warnings


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────


def get_project_id():
    """Try to get GCP project ID from env vars or gcloud config."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id
    try:
        result = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            p = result.stdout.strip()
            if p and p != "(unset)":
                return p
    except Exception:
        pass
    return None


def get_supplier_instructions(supplier_code):
    """Try to load supplier instructions from Firestore, with fallback."""
    try:
        from src.data.supplier_service import SupplierService

        service = SupplierService()
        instructions = service.get_supplier_instructions(supplier_code)
        return instructions
    except Exception as e:
        print(f"  ⚠️  Could not load supplier instructions from Firestore: {e}")
        return None


def get_suppliers_csv():
    """Try to load suppliers CSV from Firestore, fallback to Excel."""
    try:
        from src.data.supplier_service import SupplierService

        service = SupplierService()
        return service.get_suppliers_csv()
    except Exception as e:
        print(f"  ⚠️  Could not load from Firestore: {e}. Trying Excel fallback...")
        return load_suppliers_csv()


# ──────────────────────────────────────────────
#  MAIN TEST
# ──────────────────────────────────────────────


def run_full_cycle(file_path, email_body=""):
    print("=" * 80)
    print(f"  FULL CYCLE v2 TEST: {os.path.basename(file_path)}")
    print("=" * 80)

    # Init client
    project_id = get_project_id()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not project_id and not api_key:
        print("ERROR: No credentials. Set GOOGLE_CLOUD_PROJECT or GOOGLE_API_KEY.")
        sys.exit(1)
    init_client(project_id=project_id, api_key=api_key)

    # ── PHASE 1: Supplier Detection ──
    print("\n" + "─" * 40)
    print("  PHASE 1: Supplier Detection")
    print("─" * 40)

    suppliers_csv = get_suppliers_csv()
    supplier_code, confidence = detect_supplier(
        email_body=email_body,
        invoice_file_path=file_path,
        invoice_mime_type="application/pdf",
        suppliers_csv=suppliers_csv,
    )
    print(f"\n  Result: supplier_code={supplier_code}, confidence={confidence}")

    # Load supplier-specific instructions
    supplier_instructions = None
    if supplier_code and supplier_code != "UNKNOWN":
        supplier_instructions = get_supplier_instructions(supplier_code)
        if supplier_instructions:
            print(f"  📋 Supplier instructions loaded: {supplier_instructions[:80]}...")
        else:
            print(f"  ℹ️  No special instructions for supplier {supplier_code}")

    # ── PHASE 2: Invoice Extraction (v2) ──
    print("\n" + "─" * 40)
    print("  PHASE 2: Invoice Extraction (v2 prompt)")
    print("─" * 40)

    with open(file_path, "rb") as f:
        file_content = f.read()

    file_part = types.Part.from_bytes(data=file_content, mime_type="application/pdf")
    prompt_text = get_invoice_extraction_prompt(
        email_context=email_body if email_body else None, supplier_instructions=supplier_instructions, version="v2"
    )

    print("  Sending request to Gemini...")
    response = generate_content_safe(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=[file_part, types.Part.from_text(text=prompt_text)])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=pdf_response_schema, temperature=0.0
        ),
    )

    raw_json = response.text.strip()

    # Print raw model response
    print("\n  📄 Raw model response:")
    print(json.dumps(json.loads(raw_json), indent=2, ensure_ascii=False))

    # Parse into Pydantic models
    multi_order = MultiOrderResponse.model_validate_json(raw_json)
    orders = multi_order.orders
    print(f"\n  Extracted {len(orders)} order(s)")

    # ── PHASE 3: Post-Processing ──
    print("\n" + "─" * 40)
    print("  PHASE 3: Post-Processing & Validation")
    print("─" * 40)

    for i, order in enumerate(orders):
        print(f"\n  Order #{i + 1}: {order.invoice_number or 'N/A'}")
        print(f"  VAT Status: {order.line_items[0].vat_status if order.line_items else 'N/A'}")
        print(f"  Global Discount: {order.global_discount_percentage}%")
        print(f"  VAT Rate: {order.vat_rate}%")

        # Attach supplier info
        order.supplier_code = supplier_code

        # Post-process (calculate net prices + promotions)
        order = post_process_order(order)

        # Print line items
        print(f"\n  {'Description':<35} | {'Qty':>5} | {'Raw Price':>10} | {'Disc%':>6} | {'Net Price':>10}")
        print(f"  {'-' * 80}")
        for item in order.line_items:
            desc = (item.description or "")[:35]
            print(
                f"  {desc:<35} | {item.quantity:>5} | {item.raw_unit_price:>10.2f} | {item.discount_percentage:>5.1f}% | {item.final_net_price:>10.4f}"
            )

        # Validate
        print()
        warnings = validate_order(order)
        order.warnings.extend(warnings)

        if not warnings:
            print(f"\n  🎉 Order #{i + 1} passed all validations!")
        else:
            print(f"\n  ⚠️  Order #{i + 1} has {len(warnings)} warning(s)")

    print("\n" + "=" * 80)
    print("  TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    test_file = "tests-data/PQ26000005.pdf"
    if not os.path.exists(test_file):
        import glob

        files = glob.glob("tests-data/*.pdf")
        if files:
            test_file = files[0]
        else:
            print("No PDF files found in tests-data/")
            sys.exit(1)

    run_full_cycle(test_file)
