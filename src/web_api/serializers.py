from __future__ import annotations

from datetime import datetime

from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.web_api.schemas import OrderDetailDto, OrderLineItemDto, OrderListItemDto, OrderMetricsDto


def normalize_status(raw_status: str | None) -> str:
    status = str(raw_status or "").upper().strip()
    if status == "EXTRACTED":
        return "COMPLETED"
    return status or "UNKNOWN"


def isoformat_or_none(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def matches_search(order: dict, search: str) -> bool:
    if not search:
        return True

    value = search.lower()
    haystacks = [
        str(order.get("invoice_number", "")),
        str(order.get("supplier_code", "")),
        str(order.get("supplier_name", "")),
        str(order.get("sender", "")),
        str(order.get("subject", "")),
        str(order.get("filename", "")),
    ]
    for item in order.get("line_items") or []:
        haystacks.append(str(item.get("barcode", "")))
        haystacks.append(str(item.get("description", "")))
    return any(value in candidate.lower() for candidate in haystacks if candidate)


def filter_orders(
    orders: list[dict],
    *,
    search: str = "",
    statuses: list[str] | None = None,
    supplier_codes: list[str] | None = None,
    include_test: bool = False,
    date_from=None,
    date_to=None,
) -> list[dict]:
    statuses_set = {normalize_status(value) for value in (statuses or []) if value}
    supplier_codes_set = {str(value).strip() for value in (supplier_codes or []) if str(value).strip()}

    filtered: list[dict] = []
    for order in orders:
        is_test = bool(order.get("is_test", False))
        if not include_test and is_test:
            continue

        status = normalize_status(order.get("status"))
        if statuses_set and status not in statuses_set:
            continue

        supplier_code = str(order.get("supplier_code", "UNKNOWN"))
        if supplier_codes_set and supplier_code not in supplier_codes_set:
            continue

        created_at = order.get("created_at")
        created_date = created_at.date() if isinstance(created_at, datetime) else None
        if date_from and date_to and created_date and not (date_from <= created_date <= date_to):
            continue

        if not matches_search(order, search):
            continue

        enriched = dict(order)
        enriched["display_status"] = status
        filtered.append(enriched)
    return filtered


def build_order_metrics(orders: list[dict]) -> OrderMetricsDto:
    return OrderMetricsDto(
        total=len(orders),
        completed=sum(1 for order in orders if order.get("display_status") == "COMPLETED"),
        needs_review=sum(1 for order in orders if order.get("display_status") == "NEEDS_REVIEW"),
        failed=sum(1 for order in orders if order.get("display_status") == "FAILED"),
        unknown_supplier=sum(1 for order in orders if str(order.get("supplier_code", "")).upper() == "UNKNOWN"),
    )


def serialize_order_list_item(order: dict, supplier_service: SupplierService | None = None) -> OrderListItemDto:
    supplier_code = order.get("supplier_code") or "UNKNOWN"
    supplier_name = order.get("supplier_name") or "-"
    if supplier_name in {"-", "", "Unknown", "UNKNOWN"} and supplier_service and supplier_code not in {"UNKNOWN", "Unknown"}:
        supplier_data = supplier_service.get_supplier(supplier_code)
        if supplier_data:
            supplier_name = supplier_data.get("name") or supplier_name

    return OrderListItemDto(
        order_id=str(order.get("order_id", "")),
        status=normalize_status(order.get("status")),
        supplier_code=supplier_code,
        supplier_name=supplier_name,
        invoice_number=str(order.get("invoice_number", "-") or "-"),
        sender=str(order.get("sender") or order.get("ui_metadata", {}).get("sender") or "-"),
        subject=str(order.get("subject") or order.get("ui_metadata", {}).get("subject") or "-"),
        filename=str(order.get("filename") or order.get("ui_metadata", {}).get("filename") or "-"),
        created_at=isoformat_or_none(order.get("created_at")),
        line_items_count=int(order.get("line_items_count") or len(order.get("line_items") or [])),
        warnings_count=int(order.get("warnings_count") or len(order.get("warnings") or [])),
        is_test=bool(order.get("is_test", False)),
    )


def serialize_order_detail(order: dict, *, base_path: str, items_service: ItemsService | None = None) -> OrderDetailDto:
    metadata = order.get("ui_metadata", {}) or {}
    supplier_name = order.get("supplier_name") or order.get("supplier_code") or "Unknown"
    supplier_code = order.get("supplier_code") or "UNKNOWN"

    items_lookup: dict[str, str] = {}
    barcodes = [
        str(item.get("barcode", "")).strip()
        for item in order.get("line_items", [])
        if item.get("barcode")
    ]
    if items_service and barcodes:
        for item in items_service.get_items_batch(barcodes):
            barcode = str(item.get("barcode", "")).strip()
            item_code = item.get("item_code")
            if barcode and item_code:
                items_lookup[barcode] = item_code

    line_items = []
    for item in order.get("line_items", []) or []:
        barcode = str(item.get("barcode", "")).strip()
        item_code = items_lookup.get(barcode) or barcode
        line_items.append(
            OrderLineItemDto(
                barcode=barcode,
                item_code=item_code,
                description=str(item.get("description", "")),
                quantity=item.get("quantity", 0),
                final_net_price=item.get("final_net_price", 0),
            )
        )

    order_id = str(order.get("order_id", ""))
    return OrderDetailDto(
        order_id=order_id,
        status=normalize_status(order.get("status")),
        supplier_code=supplier_code,
        supplier_name=supplier_name,
        invoice_number=str(order.get("invoice_number", "-") or "-"),
        sender=str(order.get("sender") or metadata.get("sender") or "-"),
        subject=str(order.get("subject") or metadata.get("subject") or "-"),
        filename=str(order.get("filename") or metadata.get("filename") or "-"),
        created_at=isoformat_or_none(order.get("created_at") or metadata.get("created_at")),
        processing_cost_ils=float(order.get("processing_cost_ils") or 0.0),
        is_test=bool(order.get("is_test", False)),
        warnings=list(order.get("warnings") or []),
        notes=order.get("notes"),
        math_reasoning=order.get("math_reasoning"),
        qty_reasoning=order.get("qty_reasoning"),
        line_items=line_items,
        source_file_url=f"{base_path}/orders/{order_id}/source-file",
        export_url=f"{base_path}/orders/{order_id}/export.xlsx",
    )
