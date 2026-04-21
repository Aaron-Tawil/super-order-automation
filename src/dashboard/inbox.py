"""
Orders Inbox page for Streamlit dashboard.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from src.dashboard.timezone_utils import format_dashboard_dt, get_dashboard_timezone, to_dashboard_time
from src.data.orders_service import OrdersService
from src.data.processing_events_service import ProcessingEventsService
from src.data.supplier_service import SupplierService
from src.shared.config import settings
from src.shared.constants import INGESTION_SOURCE_DASHBOARD_UPLOAD, INGESTION_SOURCE_EMAIL
from src.shared.translations import get_text

MIN_DT = datetime.min.replace(tzinfo=UTC)


def _normalize_status(raw_status: str | None) -> str:
    status = str(raw_status or "").upper().strip()
    if status == "EXTRACTED":
        return "COMPLETED"
    return status or "UNKNOWN"


def _format_cost_ils(order: dict) -> float | None:
    value = order.get("processing_cost_ils")
    if value in (None, ""):
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _build_order_link(order: dict) -> str:
    base = settings.get_web_ui_url.rstrip("/")
    if order.get("record_type") in {"processing_event", "failed_order"}:
        return f"{base}/?failed_event_id={order.get('event_id', '')}"
    return f"{base}/?order_id={order.get('order_id', '')}"


def _format_ingestion_source(order: dict) -> str:
    """Return a display-friendly ingestion source label for inbox rows."""
    source = (
        str(order.get("ingestion_source") or (order.get("ui_metadata") or {}).get("ingestion_source") or "")
        .strip()
        .lower()
    )

    if source == INGESTION_SOURCE_EMAIL:
        return get_text("inbox_ingestion_source_email")
    if source == INGESTION_SOURCE_DASHBOARD_UPLOAD:
        return get_text("inbox_ingestion_source_dashboard_upload")
    return get_text("inbox_ingestion_source_unknown")


@st.cache_data(ttl=30)
def _load_orders(limit: int = 500) -> list[dict]:
    orders = OrdersService().list_orders(limit=limit)
    failed_events = ProcessingEventsService().list_failed_events(limit=limit)
    failed_order_event_ids = {
        str(order.get("event_id"))
        for order in orders
        if order.get("record_type") == "failed_order" and order.get("event_id")
    }
    failed_events = [event for event in failed_events if str(event.get("event_id")) not in failed_order_event_ids]
    combined = [*orders, *failed_events]
    return sorted(combined, key=lambda o: o.get("created_at") or o.get("updated_at") or MIN_DT, reverse=True)


@st.cache_data(ttl=300)
def _load_supplier_name_map() -> dict[str, str]:
    """Returns {supplier_code: supplier_name} for all known suppliers."""
    try:
        suppliers = SupplierService().get_all_suppliers()
        return {s["code"]: s["name"] for s in suppliers if s.get("code") and s.get("name")}
    except Exception:
        return {}


def _matches_search(order: dict, search: str) -> bool:
    if not search:
        return True

    haystacks = [
        str(order.get("invoice_number", "")),
        str(order.get("supplier_code", "")),
        str(order.get("supplier_name", "")),
        str(order.get("ingestion_source", "")),
        str(order.get("sender", "")),
        str(order.get("subject", "")),
        str(order.get("filename", "")),
        str(order.get("error", "")),
        str(order.get("stage", "")),
        str(order.get("feedback_email_status", "")),
    ]

    line_items = order.get("line_items") or []
    for item in line_items:
        haystacks.append(str(item.get("barcode", "")))
        haystacks.append(str(item.get("description", "")))

    value = search.lower()
    return any(value in h.lower() for h in haystacks if h)


def render_orders_inbox(*, show_title: bool = True, embedded: bool = False) -> None:
    widget_prefix = "dashboard_inbox" if embedded else "inbox_page"

    if show_title:
        st.title(get_text("inbox_title"))
    else:
        st.subheader(get_text("inbox_title"))
    st.caption(get_text("inbox_subtitle"))

    try:
        orders = _load_orders()
        supplier_name_map = _load_supplier_name_map()
    except Exception as e:
        st.error(get_text("inbox_load_fail", error=e))
        return

    if not orders:
        st.info(get_text("inbox_empty"))
        return

    status_col, supplier_col, range_col, include_test_col, refresh_col = st.columns([1.4, 2, 1.8, 1, 0.8])
    with status_col:
        status_options = sorted({_normalize_status(o.get("status")) for o in orders})
        selected_statuses = st.multiselect(
            get_text("inbox_filter_status"),
            options=status_options,
            default=[],
            placeholder=get_text("inbox_filter_all"),
            key=f"{widget_prefix}_status",
        )
    with supplier_col:
        # Build label→code mapping so dropdown shows names
        supplier_label_to_code: dict[str, str] = {}
        for o in orders:
            code = str(o.get("supplier_code", "UNKNOWN"))
            name = o.get("supplier_name") or supplier_name_map.get(code) or code
            label = f"{name} ({code})"
            supplier_label_to_code[label] = code
        supplier_options = sorted(supplier_label_to_code.keys())
        selected_supplier_labels = st.multiselect(
            get_text("inbox_filter_supplier"),
            options=supplier_options,
            default=[],
            placeholder=get_text("inbox_filter_all"),
            key=f"{widget_prefix}_supplier",
        )
        selected_suppliers = {supplier_label_to_code[lbl] for lbl in selected_supplier_labels}
    with range_col:
        today = datetime.now(get_dashboard_timezone()).date()
        date_range = st.date_input(
            get_text("inbox_filter_date"),
            value=(today - timedelta(days=30), today),
            key=f"{widget_prefix}_date",
        )
    with include_test_col:
        include_test = st.checkbox(get_text("inbox_include_test"), value=False, key=f"{widget_prefix}_include_test")
    with refresh_col:
        if st.button(get_text("inbox_refresh"), width="stretch", key=f"{widget_prefix}_refresh"):
            _load_orders.clear()
            st.rerun()

    filtered: list[dict] = []
    date_from = None
    date_to = None
    if isinstance(date_range, tuple | list) and len(date_range) == 2:
        date_from, date_to = date_range[0], date_range[1]

    for order in orders:
        order["is_test"] = bool(order.get("is_test", False))
        order_status = _normalize_status(order.get("status"))
        order["display_status"] = order_status
        order_supplier = str(order.get("supplier_code", "UNKNOWN"))
        created_at = to_dashboard_time(order.get("created_at"))
        created_date = created_at.date() if created_at else None

        if not include_test and order["is_test"]:
            continue
        if selected_statuses and order_status not in selected_statuses:
            continue
        if selected_suppliers and order_supplier not in selected_suppliers:
            continue
        if date_from and date_to and created_date:
            if not (date_from <= created_date <= date_to):
                continue
        filtered.append(order)

    total = len(filtered)
    failed = sum(1 for o in filtered if o.get("display_status") == "FAILED")
    needs_review = sum(1 for o in filtered if o.get("display_status") == "NEEDS_REVIEW")
    completed = sum(1 for o in filtered if o.get("display_status") == "COMPLETED")
    unknown_supplier = sum(1 for o in filtered if str(o.get("supplier_code", "")).upper() == "UNKNOWN")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(get_text("inbox_metric_total"), total)
    m2.metric(get_text("inbox_metric_completed"), completed)
    m3.metric(get_text("inbox_metric_review"), needs_review)
    m4.metric(get_text("inbox_metric_failed"), failed)
    m5.metric(get_text("inbox_metric_unknown"), unknown_supplier)

    if not filtered:
        st.info(get_text("inbox_no_results"))
        return

    rows = []
    for order in filtered:
        warnings_count = order.get("warnings_count")
        if warnings_count is None:
            warnings_count = len(order.get("warnings", []) or [])

        line_items_count = order.get("line_items_count")
        if line_items_count is None:
            line_items_count = len(order.get("line_items", []) or [])

        supplier_code = order.get("supplier_code") or "UNKNOWN"
        supplier_name = order.get("supplier_name") or supplier_name_map.get(supplier_code) or "-"

        rows.append(
            {
                "select": False,
                "created_at": format_dashboard_dt(order.get("created_at")),
                "status": order.get("display_status", "UNKNOWN"),
                "supplier": f"{supplier_name} ({supplier_code})",
                "invoice_number": order.get("invoice_number", "-"),
                "ingestion_source": _format_ingestion_source(order),
                "cost_ils": _format_cost_ils(order),
                "error": order.get("error", "-")
                if order.get("record_type") in {"processing_event", "failed_order"}
                else "-",
                "line_items": line_items_count,
                "warnings": warnings_count,
                "is_test": bool(order.get("is_test", False)),
            }
        )

    # --- Single-selection logic via session state ---
    prev_selected_key = f"{widget_prefix}_prev_selected_idx"
    prev_selected_idx = st.session_state.get(prev_selected_key)

    # Pre-set the select column from session state so only the stored row is checked
    for i, row in enumerate(rows):
        row["select"] = i == prev_selected_idx

    df = pd.DataFrame(rows)
    display_cols = [
        "select",
        "created_at",
        "status",
        "supplier",
        "invoice_number",
        "ingestion_source",
        "cost_ils",
        "error",
        "line_items",
        "warnings",
        "is_test",
    ]

    # Dynamic key: changes when selection changes, which resets editor internal state
    editor_key = f"{widget_prefix}_orders_editor_{prev_selected_idx}"
    edited_df = st.data_editor(
        df[display_cols],
        width="stretch",
        hide_index=True,
        key=editor_key,
        disabled=[
            "created_at",
            "status",
            "supplier",
            "invoice_number",
            "cost_ils",
            "error",
            "line_items",
            "warnings",
        ],
        column_config={
            "select": st.column_config.CheckboxColumn(get_text("inbox_col_select")),
            "created_at": st.column_config.TextColumn(get_text("inbox_col_created_at")),
            "status": st.column_config.TextColumn(get_text("inbox_col_status")),
            "supplier": st.column_config.TextColumn(get_text("inbox_col_supplier")),
            "invoice_number": st.column_config.TextColumn(get_text("inbox_col_invoice")),
            "ingestion_source": st.column_config.TextColumn(get_text("inbox_col_ingestion_source")),
            "cost_ils": st.column_config.NumberColumn(get_text("inbox_col_cost"), format="%.3f ₪"),
            "error": st.column_config.TextColumn(get_text("inbox_col_error")),
            "line_items": st.column_config.NumberColumn(get_text("inbox_col_line_items")),
            "warnings": st.column_config.NumberColumn(get_text("inbox_col_warnings")),
            "is_test": st.column_config.CheckboxColumn(get_text("inbox_col_is_test")),
        },
    )

    checked_indices = [int(i) for i, selected in enumerate(edited_df["select"].tolist()) if bool(selected)]

    # Enforce single selection: detect changes and rerun with new key to reset editor
    if len(checked_indices) > 1:
        new_idx = next((i for i in checked_indices if i != prev_selected_idx), checked_indices[-1])
        st.session_state[prev_selected_key] = new_idx
        st.rerun()
    elif len(checked_indices) == 1 and checked_indices[0] != prev_selected_idx:
        st.session_state[prev_selected_key] = checked_indices[0]
        st.rerun()
    elif len(checked_indices) == 0 and prev_selected_idx is not None:
        st.session_state[prev_selected_key] = None
        st.rerun()

    selected_orders = [filtered[i] for i in checked_indices if i < len(filtered)]

    updates: dict[str, bool] = {}
    for idx, row in edited_df.iterrows():
        if idx >= len(filtered):
            continue
        order = filtered[idx]
        if order.get("record_type") in {"processing_event", "failed_order"}:
            continue
        order_id = str(order.get("order_id", "")).strip()
        if not order_id:
            continue
        new_is_test = bool(row["is_test"])
        original_is_test = bool(order.get("is_test", False))
        if new_is_test != original_is_test:
            updates[order_id] = new_is_test

    save_col, open_col = st.columns([1, 1])
    with save_col:
        if st.button(
            get_text("inbox_save_test_changes"),
            width="stretch",
            type="primary" if updates else "secondary",
            disabled=not updates,
            key=f"{widget_prefix}_save_changes",
        ):
            updated, failed = OrdersService().update_order_test_flags(updates)
            _load_orders.clear()
            st.cache_data.clear()
            if updated:
                st.success(get_text("inbox_test_update_success", count=updated))
            if failed:
                st.warning(get_text("inbox_test_update_failed", count=failed))
            st.rerun()

    with open_col:
        if len(selected_orders) == 1:
            selected_order = selected_orders[0]
            link = _build_order_link(selected_order)
            st.link_button(
                get_text("inbox_open_order"),
                url=link,
                type="primary",
                width="stretch",
            )
        else:
            st.button(
                get_text("inbox_open_order"),
                type="secondary",
                width="stretch",
                disabled=True,
                key=f"{widget_prefix}_open_order_disabled",
            )
