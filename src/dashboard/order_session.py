"""
Order Session View — Dedicated full-page view for reviewing and editing a single order.

This module renders the landing view when a user opens an email link (?session=<id>)
or opens an order from the inbox. It replaces the old inline editor in app.py.
"""

from __future__ import annotations

import io
import os

import pandas as pd
import streamlit as st

from src.data.items_service import ItemsService
from src.data.orders_service import OrdersService
from src.data.supplier_service import SupplierService
from src.ingestion.gcs_writer import download_file_from_gcs
from src.shared.logger import get_logger
from src.shared.translations import get_text
from src.shared.utils import get_mime_type

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_order_session() -> None:  # noqa: C901
    """Render the full-page order session view."""

    # ------------------------------------------------------------------
    # Guard: must have extracted_data in session state
    # ------------------------------------------------------------------
    if "extracted_data" not in st.session_state:
        st.info(get_text("session_no_order"))
        if st.button(get_text("order_session_back"), type="secondary"):
            st.session_state["page"] = "inbox"
            st.rerun()
        return

    data: dict = st.session_state["extracted_data"]
    if "is_test" not in data:
        data["is_test"] = False

    # Extract UI metadata that was moved inside the order document
    metadata: dict = data.get("ui_metadata", {})
    order_id: str | None = st.session_state.get("active_order_id")

    supplier_name = data.get("supplier_name") or ""
    supplier_code = data.get("supplier_code") or "Unknown"

    # If supplier_name is missing (e.g. legacy order), look it up live
    if (not supplier_name or supplier_name in ("Unknown", "UNKNOWN")) and supplier_code not in ("Unknown", "UNKNOWN", None):
        try:
            s_data = SupplierService().get_supplier(supplier_code)
            if s_data:
                supplier_name = s_data.get("name", "") or supplier_code
        except Exception:
            pass
    if not supplier_name:
        supplier_name = supplier_code if supplier_code not in ("Unknown", "UNKNOWN") else "Unknown"

    # ------------------------------------------------------------------
    # Top nav bar: Back button (right side in RTL) + subtitle
    # ------------------------------------------------------------------
    nav_back_col, nav_title_col = st.columns([1, 3])
    with nav_back_col:
        if st.button(get_text("order_session_back"), type="secondary", width="stretch"):
            for key in [
                "extracted_data",
                "session_metadata",
                "from_email",
                "active_session_id",
                "active_order_id",
            ]:
                st.session_state.pop(key, None)
            for key in list(st.session_state.keys()):
                if key.startswith("order_type_edit_"):
                    del st.session_state[key]
            st.query_params.clear()
            st.session_state["page"] = "inbox"
            st.rerun()

    # ------------------------------------------------------------------
    # Validation warnings — shown at the very top
    # ------------------------------------------------------------------
    if data.get("warnings"):
        for w in data["warnings"]:
            st.error(w)

    # ------------------------------------------------------------------
    # Order header card
    # ------------------------------------------------------------------
    raw_status = data.get("status") or metadata.get("status") or "UNKNOWN"
    if str(raw_status).upper() == "EXTRACTED":
        raw_status = "COMPLETED"
    display_status = str(raw_status).upper()

    cost_ils = data.get("processing_cost_ils", 0.0) or 0.0
    invoice_number = str(data.get("invoice_number", "-") or "-").strip() or "-"
    created_at = data.get("created_at") or metadata.get("created_at")
    if hasattr(created_at, "strftime"):
        created_at_str = created_at.strftime("%Y-%m-%d %H:%M")
    elif created_at:
        created_at_str = str(created_at)[:16]
    else:
        created_at_str = "-"

    # ------------------------------------------------------------------
    # Order header card — RTL-friendly: status (right) → invoice → sender → supplier (left)
    # ------------------------------------------------------------------
    order_type_key = f"order_type_edit_{order_id or data.get('invoice_number') or 'manual'}"
    if order_type_key not in st.session_state:
        st.session_state[order_type_key] = bool(data.get("is_test", False))

    with st.container(border=True):
        st.markdown(f"### 🧾 {get_text('order_session_header_title')}")
        # In RTL, col1 renders on the RIGHT. So: status | invoice | supplier
        col_status, col_invoice, col_supplier = st.columns(3)

        # Helper to control text size and color of captions below metrics
        def _custom_caption(text: str) -> None:
            st.markdown(
                f"<p style='font-size: 20px; color: #888; margin-top: -15px;'>{text}</p>",
                unsafe_allow_html=True,
            )

        with col_supplier:
            st.metric(get_text("metric_supplier"), supplier_name)
            _custom_caption(f"קוד: {supplier_code}")
        with col_invoice:
            st.metric(get_text("metric_invoice"), invoice_number)
            if created_at_str != "-":
                _custom_caption(f"📅 {created_at_str}")
        with col_status:
            st.metric(get_text("order_session_status"), display_status)
            _custom_caption(f"💰 {cost_ils:.3f} ₪")

        st.divider()
        # Order type toggle inside the card — cleaner than floating it outside
        type_col, _ = st.columns([2, 2])
        with type_col:
            selected_is_test = st.radio(
                get_text("order_type_label"),
                options=[False, True],
                format_func=lambda val: get_text("order_type_test") if val else get_text("order_type_real"),
                horizontal=True,
                key=order_type_key,
            )

    if selected_is_test != bool(data.get("is_test", False)):
        data["is_test"] = bool(selected_is_test)
        st.session_state["extracted_data"] = data
        metadata["is_test"] = bool(selected_is_test)
        st.session_state["session_metadata"] = metadata

        order_id_for_update = st.session_state.get("active_order_id")
        try:
            if order_id_for_update:
                OrdersService().update_order_test_flag(order_id_for_update, bool(selected_is_test))
        except Exception:
            pass
        st.cache_data.clear()
        st.success(get_text("order_type_updated"))
        st.rerun()

    # ------------------------------------------------------------------
    # AI Insights (collapsible)
    # ------------------------------------------------------------------
    p2_notes = data.get("notes")
    math_reasoning = data.get("math_reasoning")
    qty_reasoning = data.get("qty_reasoning")

    if p2_notes or math_reasoning or qty_reasoning:
        with st.expander("🔍 תובנות והסברי AI", expanded=False):
            if p2_notes:
                st.markdown(f"**הערות חילוץ:**\n{p2_notes}")
            if math_reasoning:
                st.warning(f"**הסבר חישוב (מתמטי):**\n{math_reasoning}")
            if qty_reasoning:
                st.warning(f"**הסבר כמויות:**\n{qty_reasoning}")

    # ------------------------------------------------------------------
    # Line Items Table (read-only)
    # ------------------------------------------------------------------
    st.divider()
    st.subheader(get_text("editor_title"))

    items_service = ItemsService()
    display_data = []

    all_barcodes = [
        str(item.get("barcode", "")).strip()
        for item in data.get("line_items", [])
        if item.get("barcode")
    ]
    items_map: dict[str, str] = {}

    if all_barcodes:
        db_items = items_service.get_items_batch(all_barcodes)
        for db_item in db_items:
            b = str(db_item.get("barcode"))
            code = db_item.get("item_code")
            if b and code:
                items_map[b] = code

    for item in data.get("line_items", []):
        barcode = str(item.get("barcode", "")).strip() if item.get("barcode") else ""
        item_code_val = barcode
        if barcode in items_map:
            item_code_val = items_map[barcode]
        elif barcode.startswith("0") and barcode.lstrip("0") in items_map:
            item_code_val = items_map[barcode.lstrip("0")]

        display_data.append(
            {
                "item_code": item_code_val,
                "description": item.get("description", ""),
                "quantity": item.get("quantity", 0),
                "final_net_price": item.get("final_net_price", 0),
                "_barcode": barcode,
            }
        )

    df = pd.DataFrame(display_data)
    display_cols = ["item_code", "description", "quantity", "final_net_price"]
    df_display = df[display_cols].copy() if not df.empty else pd.DataFrame(columns=display_cols)

    # Rename columns to Hebrew for display
    df_display_heb = df_display.rename(columns={
        "item_code": get_text("col_item_code"),
        "description": get_text("col_description"),
        "quantity": get_text("col_qty"),
        "final_net_price": get_text("col_net_price"),
    })
    st.dataframe(df_display_heb, width="stretch", hide_index=True)

    # ------------------------------------------------------------------
    # Action bar: Download Excel only (reset button removed — use back arrow instead)
    # ------------------------------------------------------------------
    st.divider()

    # Generate Excel from the display dataframe
    excel_data = None
    try:
        excel_df = df_display[["item_code", "quantity", "final_net_price"]].copy()
        excel_df.columns = ["קוד פריט", "כמות", "מחיר נטו"]
        buffer = io.BytesIO()
        excel_df.to_excel(buffer, index=False)
        buffer.seek(0)
        excel_data = buffer.getvalue()
    except Exception as e:
        logger.error(f"Excel generation failed: {e}")

    dl_col, src_col = st.columns([2, 1])

    with dl_col:
        if excel_data:
            st.download_button(
                label=get_text("order_session_finish"),
                data=excel_data,
                file_name=f"order_{data.get('invoice_number', 'export')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                width="stretch",
            )
        else:
            st.button(
                get_text("order_session_finish"),
                disabled=True,
                type="primary",
                width="stretch",
                help="Error generating Excel",
            )

    with src_col:
        source_uri = metadata.get("source_file_uri") or data.get("gcs_uri")
        src_filename = metadata.get("filename") or data.get("filename") or ""

        # Build a safe, informative download filename: order_SUPPLIER_INVOICE_DATE.ext
        def _safe(s: str) -> str:
            import re  # noqa: PLC0415
            return re.sub(r"[^\w\-]", "_", str(s or "unknown")).strip("_") or "unknown"

        # Determine extension from stored filename or from GCS URI blob name
        src_ext = os.path.splitext(src_filename)[1] if src_filename else ""
        if not src_ext and source_uri:
            src_ext = os.path.splitext(source_uri.split("/")[-1])[1]
        if not src_ext:
            src_ext = ".pdf"  # fallback

        date_str = created_at_str[:10].replace("-", "") if created_at_str != "-" else ""
        safe_download_name = (
            f"order_{_safe(supplier_code)}_{_safe(invoice_number)}"
            + (f"_{date_str}" if date_str else "")
            + src_ext
        )

        if source_uri:
            if st.button(get_text("order_session_download_source"), width="stretch", type="secondary"):
                with st.spinner("מוריד קובץ מקורי..."):
                    try:
                        tmp = f"tmp_src_{os.getpid()}{src_ext}"
                        if download_file_from_gcs(source_uri, tmp):
                            with open(tmp, "rb") as fh:
                                src_bytes = fh.read()
                            os.remove(tmp)
                            st.session_state["_src_file_bytes"] = src_bytes
                            st.session_state["_src_file_name"] = safe_download_name
                            st.rerun()
                        else:
                            st.error("לא ניתן להוריד את הקובץ המקורי.")
                    except Exception as e:
                        st.error(f"שגיאה: {e}")
        else:
            st.button(get_text("order_session_download_source"), disabled=True, width="stretch", type="secondary",
                      help="הקובץ המקורי אינו זמין")

    # Serve the downloaded file as a real download_button on the next render
    if "_src_file_bytes" in st.session_state:
        st.download_button(
            label=get_text("order_session_download_source"),
            data=st.session_state["_src_file_bytes"],
            file_name=st.session_state.get("_src_file_name", "original_file"),
            type="secondary",
        )
        del st.session_state["_src_file_bytes"]

    # ------------------------------------------------------------------
    # New Items Section — shown when new items were added to the DB for this order.
    # Data comes from session metadata (email path) OR from order data (Firestore path).
    # ------------------------------------------------------------------
    new_items_data = metadata.get("new_items") or data.get("new_items") or []
    if new_items_data:
        st.divider()
        st.subheader(get_text("new_items_section_title"))
        st.caption(get_text("new_items_section_caption"))

        from src.shared.product_pricing import calculate_sell_price  # noqa: PLC0415

        new_items_display = []
        for item in new_items_data:
            barcode = str(item.get("barcode", "")).strip() if item.get("barcode") else ""
            final_net_price = item.get("final_net_price", 0) or 0
            sell_price = calculate_sell_price(final_net_price) if final_net_price else 0
            new_items_display.append(
                {
                    "ברקוד": barcode,
                    "שם פריט": item.get("description", ""),
                    "ברקוד 2": barcode,
                    "מכירה": sell_price,
                    "עלות נטו": final_net_price,
                    "מספר ספק": supplier_code,
                }
            )

        new_items_df = pd.DataFrame(new_items_display)
        st.dataframe(new_items_df, width="stretch", hide_index=True)

        try:
            output_path = f"temp_new_items_{data.get('invoice_number', 'gen')}.xlsx"
            new_items_df.to_excel(output_path, index=False)
            with open(output_path, "rb") as f:
                new_items_excel_data = f.read()
            if os.path.exists(output_path):
                os.remove(output_path)

            st.download_button(
                label=get_text("btn_download_new_items"),
                data=new_items_excel_data,
                file_name=f"new_items_{data.get('invoice_number', 'export')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="secondary",
                width="stretch",
            )

            added_barcodes = metadata.get("added_items_barcodes", [])
            if added_barcodes:
                if st.button(
                    get_text("btn_revert_items", count=len(added_barcodes)),
                    type="secondary",
                    width="stretch",
                ):
                    try:
                        deleted = items_service.delete_items_by_barcodes(added_barcodes)
                        st.success(get_text("msg_revert_success", count=deleted))
                        
                        metadata["added_items_barcodes"] = []
                        data["new_items"] = []
                        if "ui_metadata" not in data:
                            data["ui_metadata"] = metadata
                        data["ui_metadata"] = metadata

                        st.session_state["extracted_data"] = data
                        
                        # Persist to permanent orders collection
                        if order_id:
                            OrdersService().update_order_data(
                                order_id, 
                                {"new_items": [], "ui_metadata": metadata}
                            )
                        st.rerun()
                    except Exception as e:
                        st.error(get_text("msg_revert_fail", error=e))
        except Exception as e:
            logger.error(f"New items Excel generation failed: {e}")

    # ------------------------------------------------------------------
    # 🧪 Extraction Playground
    # ------------------------------------------------------------------
    st.divider()
    with st.container(border=True):
        st.markdown("#### 🧪 מגרש ניסויים: הוראות חילוץ AI")

        # --- Load current saved instructions ---
        saved_instructions = ""
        can_save = supplier_code and supplier_code not in ("Unknown", "UNKNOWN")
        try:
            if can_save:
                instr = SupplierService().get_supplier_instructions(supplier_code)
                if instr:
                    saved_instructions = instr
        except Exception:
            pass

        # Status badge
        if saved_instructions:
            st.success(f"✅ יש הוראות שמורות לספק **{supplier_name}**")
        elif can_save:
            st.info("⚪ אין הוראות שמורות עדיין לספק זה — כתוב הוראות ולחץ 'שמור כקבוע' לאחר ניסוי.")
        else:
            st.warning("⚠️ הספק לא זוהה (UNKNOWN) — לא ניתן לשמור הוראות קבועות.")

        # Instructions editor — pre-filled with saved value
        playground_instr_key = f"playground_instr_{order_id or supplier_code or 'draft'}"
        if playground_instr_key not in st.session_state:
            st.session_state[playground_instr_key] = saved_instructions

        draft_instructions = st.text_area(
            "הוראות מיוחדות ל-AI:",
            placeholder=(
                "לדוגמה: 'התעלם מסעיפי ביטוח' או 'המחיר ביחידות הוא ברוטו כולל מע\"מ'"
            ),
            height=140,
            key=playground_instr_key,
            help="הוראות אלו יישלחו ל-AI כהקשר נוסף בשלב החילוץ. ניתן לנסות הגדרות שונות ולהשוות."
        )

        # Action buttons row
        source_uri = metadata.get("source_file_uri") or data.get("gcs_uri")
        has_retried = bool(st.session_state.get("playground_result"))

        btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 2])

        with btn_col1:
            run_btn = st.button(
                "🔄 נסה עם ההוראות",
                type="primary",
                width="stretch",
                disabled=not source_uri,
                help=None if source_uri else "קובץ מקור לא נמצא — לא ניתן להפעיל מחדש."
            )

        with btn_col2:
            adopt_btn = st.button(
                "✅ אמץ תוצאות",
                type="secondary",
                width="stretch",
                disabled=not has_retried,
                help="העתק את תוצאות הניסוי להזמנה הפעילה ושמור ב-Firestore.",
            )

        with btn_col3:
            save_btn = st.button(
                "💾 שמור כהוראות קבועות",
                type="secondary",
                width="stretch",
                disabled=(not has_retried or not can_save),
                help=(
                    "שמור את ההוראות שנוסו כהוראות הקבועות של הספק."
                    if can_save else
                    "לא ניתן לשמור — ספק לא מזוהה."
                ),
            )

        # --- Run the extraction ---
        if run_btn:
            with st.spinner("מריץ AI מחדש עם ההוראות... זה עשוי לקחת כ-30 שניות"):
                try:
                    temp_path = "temp_playground_file"
                    filename_retry = metadata.get("filename") or data.get("ui_metadata", {}).get("filename", "unknown.pdf")
                    if "." in filename_retry:
                        temp_path += os.path.splitext(filename_retry)[1]

                    if download_file_from_gcs(source_uri, temp_path):
                        from src.core.pipeline import ExtractionPipeline  # noqa: PLC0415
                        from src.extraction.vertex_client import init_client  # noqa: PLC0415

                        init_client()
                        pipeline = ExtractionPipeline()
                        result = pipeline.run_pipeline(
                            file_path=temp_path,
                            mime_type=get_mime_type(filename_retry),
                            force_supplier_instructions=draft_instructions,
                        )
                        new_order = result.orders[0] if result.orders else None

                        if new_order:
                            st.session_state["playground_result"] = new_order.model_dump()
                            st.session_state["playground_instructions"] = draft_instructions
                            st.success("✅ הניסוי הצליח! ראה השוואה למטה.")
                            st.rerun()
                        else:
                            st.error(get_text("phase_extract_fail"))

                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    else:
                        st.error(get_text("retry_fail_download"))
                except Exception as e:
                    st.error(get_text("error_general", error=e))
                    import traceback  # noqa: PLC0415
                    st.code(traceback.format_exc())

        # --- Adopt playground results into live order ---
        if adopt_btn and has_retried:
            playground_data = st.session_state["playground_result"]

            # MERGE: start from the current live order to preserve Firestore-only
            # fields like created_at, gcs_uri, status, etc.
            merged = dict(data)  # copy of current live order
            
            # Fields to bring in from the new extraction result
            EXTRACTED_FIELDS = (
                "line_items", "invoice_number", "currency", "vat_status",
                "global_discount_percentage", "total_invoice_discount_amount",
                "document_total_with_vat", "document_total_without_vat", "document_total_quantity",
                "is_math_valid", "math_reasoning", "is_qty_valid", "qty_reasoning",
                "notes", "warnings", "processing_cost", "processing_cost_ils",
                "usage_metadata", "ai_metadata",
                "supplier_name", "supplier_code", "supplier_global_id",
                "supplier_email", "supplier_phone",
            )
            for field in EXTRACTED_FIELDS:
                if field in playground_data:
                    merged[field] = playground_data[field]

            # Always enforce the fully-resolved supplier_name so "Unknown" is
            # never written back when the code is known.
            resolved_code = merged.get("supplier_code") or supplier_code
            resolved_name = merged.get("supplier_name") or ""
            if (not resolved_name or resolved_name.upper() in ("UNKNOWN", "")) and resolved_code not in ("Unknown", "UNKNOWN", None, ""):
                try:
                    s_data = SupplierService().get_supplier(resolved_code)
                    if s_data and s_data.get("name"):
                        resolved_name = s_data["name"]
                except Exception:
                    pass
            if resolved_name and resolved_name.upper() not in ("UNKNOWN", ""):
                merged["supplier_name"] = resolved_name

            # Preserve ui_metadata
            merged["ui_metadata"] = metadata

            st.session_state["extracted_data"] = merged
            st.session_state.pop("playground_result", None)
            st.session_state.pop("playground_instructions", None)
            if order_id:
                OrdersService().update_order_data(order_id, merged)
            st.success("✅ תוצאות הניסוי אומצו והזמנה עודכנה!")
            st.rerun()

        # --- Save instructions permanently ---
        if save_btn and has_retried and can_save:
            used_instructions = st.session_state.get("playground_instructions", draft_instructions)
            try:
                ok = SupplierService().update_supplier_instructions(supplier_code, used_instructions)
                if ok:
                    st.success(f"💾 הוראות נשמרו לספק **{supplier_name}** ({supplier_code})!")
                else:
                    st.error("שגיאה בשמירת ההוראות.")
            except Exception as e:
                st.error(get_text("error_general", error=e))

        # --- Side-by-side comparison ---
        if has_retried:
            st.divider()
            st.markdown("##### 📊 השוואה: מקורי vs ניסוי")

            pg = st.session_state["playground_result"]

            # Summary metrics row
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric(
                    "מחיר עיבוד (מקורי)",
                    f"{data.get('processing_cost_ils', 0):.3f} ₪",
                )
            with m2:
                st.metric(
                    "מחיר עיבוד (ניסוי)",
                    f"{pg.get('processing_cost_ils', 0):.3f} ₪",
                )
            with m3:
                math_orig = "✅" if data.get("is_math_valid") else ("❌" if data.get("is_math_valid") is False else "—")
                math_new  = "✅" if pg.get("is_math_valid") else ("❌" if pg.get("is_math_valid") is False else "—")
                st.metric("וולידציה מתמטית", f"{math_orig} → {math_new}")
            with m4:
                qty_orig = "✅" if data.get("is_qty_valid") else ("❌" if data.get("is_qty_valid") is False else "—")
                qty_new  = "✅" if pg.get("is_qty_valid") else ("❌" if pg.get("is_qty_valid") is False else "—")
                st.metric("וולידציית כמויות", f"{qty_orig} → {qty_new}")

            # Warnings
            orig_warns = data.get("warnings") or []
            new_warns  = pg.get("warnings") or []
            if orig_warns or new_warns:
                w_col1, w_col2 = st.columns(2)
                with w_col1:
                    if orig_warns:
                        for w in orig_warns:
                            st.warning(f"🔵 {w}")
                with w_col2:
                    if new_warns:
                        for w in new_warns:
                            st.warning(f"🟢 {w}")
                    elif orig_warns:
                        st.success("🟢 אין אזהרות חדשות!")

            orig_items = data.get("line_items", [])
            new_items  = pg.get("line_items", [])

            def _items_to_df(items: list) -> pd.DataFrame:
                rows = []
                for it in items:
                    rows.append({
                        "ברקוד": it.get("barcode") or "-",
                        "תיאור": (it.get("description") or "")[:35],
                        "כמות": it.get("quantity", ""),
                        "מחיר נטו": it.get("final_net_price", ""),
                    })
                return pd.DataFrame(rows)

            cmp_orig, cmp_new = st.columns(2)
            with cmp_orig:
                st.markdown(f"**🔵 מקורי** ({len(orig_items)} שורות)")
                st.dataframe(_items_to_df(orig_items), width="stretch", hide_index=True)
            with cmp_new:
                st.markdown(f"**🟢 אחרי ניסוי** ({len(new_items)} שורות)")
                st.dataframe(_items_to_df(new_items), width="stretch", hide_index=True)
