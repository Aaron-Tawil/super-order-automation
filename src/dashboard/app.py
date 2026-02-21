"""
Super Order Automation - Dashboard

Streamlit web UI for viewing and editing extracted order data.
Supports:
- Loading from email session (via ?session=<id> URL parameter)
- Manual file upload via API
"""

import os
import sys

import pandas as pd
import requests
import streamlit as st

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import find_dotenv, load_dotenv

from src.core.processor import OrderProcessor
from src.dashboard import items_management, supplier_management
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.export.excel_generator import generate_excel_from_order
from src.extraction.vertex_client import detect_supplier, init_client
from src.ingestion.gcs_writer import download_file_from_gcs, upload_to_gcs
from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder, LineItem
from src.shared.session_store import get_session, update_session_metadata, update_session_order
from src.shared.translations import get_text

# Configure logger
logger = get_logger(__name__)

# Verify connection
if not settings.GEMINI_API_KEY and not settings.PROJECT_ID:
    logger.warning("WARNING: Neither GEMINI_API_KEY nor GCP_PROJECT_ID found.")

# Page config
# Page config
st.set_page_config(page_title=get_text("dashboard_title"), layout="wide", initial_sidebar_state="expanded")


# Load external CSS
def load_css(file_path):
    with open(file_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


css_path = os.path.join(os.path.dirname(__file__), "styles.css")
load_css(css_path)

# --- Session Loading Logic ---
# Check for session token in URL (from email link)
query_params = st.query_params
session_id = query_params.get("session")

if session_id and "extracted_data" not in st.session_state:
    session = get_session(session_id)
    if session:
        # Load order data from session (already a dict from JSON file)
        order = session["order"]
        metadata = session.get("metadata", {})

        # order is already a dict (loaded from JSON file)
        st.session_state["extracted_data"] = order
        st.session_state["session_metadata"] = metadata
        st.session_state["from_email"] = True
        st.success(get_text("dashboard_intro_email", filename=metadata.get("subject", "Unknown")))
    else:
        st.error(get_text("session_expired"))

# --- Navigation ---
if "page" not in st.session_state:
    st.session_state["page"] = "dashboard"

# Sidebar for navigation
with st.sidebar:
    st.title(get_text("nav_title"))
    if st.button(get_text("nav_dashboard"), width="stretch"):
        st.session_state["page"] = "dashboard"
        st.rerun()

    if st.button(get_text("nav_suppliers"), width="stretch"):
        st.session_state["page"] = "suppliers"
        st.rerun()

    if st.button(get_text("nav_items"), width="stretch"):
        st.session_state["page"] = "items"
        st.rerun()

    st.divider()
    # Debug Info
    if settings.GEMINI_API_KEY or settings.PROJECT_ID:
        st.sidebar.success("AI מחובר למערכת ✅")  # More meaningful text
    else:
        st.sidebar.error("מפתח AI חסר ❌")

# --- Page Routing ---
if st.session_state["page"] == "suppliers":
    supplier_management.main()
    st.stop()  # Stop execution here for this page

if st.session_state["page"] == "items":
    items_management.render_items_management_page()
    st.stop()


# --- Dashboard Logic ---
# --- Header ---
st.title(get_text("dashboard_title"))

# Show different intro based on source
if st.session_state.get("from_email"):
    metadata = st.session_state.get("session_metadata", {})
    st.info(get_text("dashboard_intro_email", filename=metadata.get("filename", "email")))
else:
    st.markdown(get_text("dashboard_intro_no_email"))

# Validation Warnings
if "extracted_data" in st.session_state:
    order_data = st.session_state["extracted_data"]
    if order_data.get("warnings"):
        for w in order_data["warnings"]:
            st.error(w)

# --- File Upload Section (only show if not from email) ---
if not st.session_state.get("from_email"):
    uploaded_file = st.file_uploader(get_text("upload_label"), type=["pdf", "xlsx", "xls"])

    if uploaded_file is not None:
        if st.button(get_text("btn_extract"), type="primary", width="stretch"):
            with st.spinner(get_text("spinner_processing")):
                try:
                    # 1. Save to Temp
                    temp_path = f"acc_{uploaded_file.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    # Determine MIME type
                    if uploaded_file.name.lower().endswith(".xlsx"):
                        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    elif uploaded_file.name.lower().endswith(".xls"):
                        mime_type = "application/vnd.ms-excel"
                    else:
                        mime_type = "application/pdf"

                    # Init Services
                    # Using global settings implicitly in init_client
                    init_client()

                    # 2. Run Pipeline
                    from src.core.pipeline import ExtractionPipeline
                    
                    pipeline = ExtractionPipeline()
                    result = pipeline.run_pipeline(
                        file_path=temp_path,
                        mime_type=mime_type,
                        email_metadata={"body": "Attached is the invoice."} # Minimal Context
                    )
                    
                    order = result.orders[0] if result.orders else None

                    if result.supplier_code != "UNKNOWN":
                        st.info(get_text("phase_1_identified", name=result.supplier_name, code=result.supplier_code))
                    else:
                        st.warning(get_text("phase_1_unknown"))

                    if order:
                        if result.detection_method == "extraction_fallback":
                             st.success(get_text("phase_fallback_success", code=result.supplier_code))
                                
                        if result.new_items_added > 0:
                             st.info(get_text("new_items_found", count=len(result.new_items_data)))
                             st.success(get_text("new_items_added", count=result.new_items_added))
                             
                        # 5. Upload to GCS (for Retry functionality)
                        try:
                            source_uri = upload_to_gcs(temp_path, uploaded_file.name)
                        except Exception as e:
                            st.warning(get_text("gcs_upload_fail", error=e))
                            source_uri = None

                        # 6. Save to Session
                        session_metadata = {
                            "filename": uploaded_file.name,
                            "source_file_uri": source_uri,
                            "added_items_barcodes": result.added_barcodes,
                            "new_items": result.new_items_data,  # For dashboard new items section
                            "from_manual_upload": True,
                            "phase1_reasoning": result.phase1_reasoning,
                        }

                        st.session_state["extracted_data"] = order.model_dump()
                        st.session_state["session_metadata"] = session_metadata
                        st.session_state["from_email"] = False  # It is manual, but we treat it as loaded now

                        # Cleanup
                        if os.path.exists(temp_path):
                            os.remove(temp_path)

                        st.rerun()

                    else:
                        st.error(get_text("phase_extract_fail"))

                except Exception as e:
                    st.error(get_text("error_general", error=e))
                    import traceback

                    st.code(traceback.format_exc())

# --- Display & Edit Logic ---
if "extracted_data" in st.session_state:
    data = st.session_state["extracted_data"]

    st.divider()

    # Header Info
    c1, c2, c3 = st.columns(3)

    # Use supplier info from order object if available
    supplier_name = data.get("supplier_name") or "Unknown"
    supplier_code = data.get("supplier_code") or "Unknown"

    c1.metric(get_text("metric_supplier"), f"{supplier_name} ({supplier_code})")
    c2.metric(get_text("metric_invoice"), data.get("invoice_number", "Unknown"))
    
    # Cost Display
    cost_ils = data.get("processing_cost_ils", 0.0)
    cost_usd = data.get("processing_cost", 0.0)
    c3.metric("עלות AI (משוער)", f"{cost_ils:.3f} ₪")
    
    # AI Insights Section
    metadata = st.session_state.get("session_metadata", {})
    p1_reasoning = metadata.get("phase1_reasoning")
    p2_notes = data.get("notes")
    math_reasoning = data.get("math_reasoning")
    qty_reasoning = data.get("qty_reasoning")
    
    if p1_reasoning or p2_notes or math_reasoning or qty_reasoning:
        with st.expander("🔍 תובנות והסברי AI", expanded=True):
            if p1_reasoning:
                st.info(f"**זיהוי ספק:** {p1_reasoning}")
            
            if p2_notes:
                st.markdown(f"**הערות חילוץ:**\n{p2_notes}")
            
            if math_reasoning:
                st.warning(f"**הסבר חישוב (מתמטי):**\n{math_reasoning}")
            
            if qty_reasoning:
                st.warning(f"**הסבר כמויות:**\n{qty_reasoning}")

    # Line Items Editor
    st.subheader(get_text("editor_title"))
    st.caption(get_text("editor_caption"))

    # Create a display dataframe with only the columns shown in the output Excel
    # The Excel has: קוד פריט (item_code), כמות (quantity), מחיר נטו (final_net_price)
    items_service = ItemsService()
    display_data = []

    # Batch lookup for all barcodes
    all_barcodes = [str(item.get("barcode", "")).strip() for item in data["line_items"] if item.get("barcode")]
    items_map = {}  # Map barcode -> db_item_code

    if all_barcodes:
        db_items = items_service.get_items_batch(all_barcodes)
        for db_item in db_items:
            b = str(db_item.get("barcode"))
            code = db_item.get("item_code")
            if b and code:
                items_map[b] = code

    for item in data["line_items"]:
        barcode = str(item.get("barcode", "")).strip() if item.get("barcode") else ""
        item_code_val = barcode  # Default to barcode

        # Use batched lookup result
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
                # Keep barcode hidden for Excel generation
                "_barcode": barcode,
            }
        )

    df = pd.DataFrame(display_data)

    # Only show user-facing columns (not internal _barcode)
    display_cols = ["item_code", "description", "quantity", "final_net_price"]
    if not df.empty:
        df_display = df[display_cols].copy()
    else:
        df_display = pd.DataFrame(columns=display_cols)

    edited_df = st.data_editor(
        df_display,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "item_code": st.column_config.TextColumn(get_text("col_item_code")),
            "description": st.column_config.TextColumn(get_text("col_description"), disabled=True),
            "quantity": st.column_config.NumberColumn(get_text("col_qty"), min_value=0),
            "final_net_price": st.column_config.NumberColumn(get_text("col_net_price"), format="%.2f"),
        },
    )

    st.divider()

    # Export Section
    col1, col2 = st.columns([1, 3])
    # Col 1: Download (Right)
    # Col 2: Clear (Left)
    # Natural flow for RTL - Download is rightmost.

    with col1:
        # Generate Excel Data for Download immediately
        # The table now shows exactly the columns in the output Excel
        excel_data = None
        try:
            # Create Excel directly from the edited table
            # Columns are: item_code → קוד פריט, quantity → כמות, final_net_price → מחיר נטו
            # Filter only the columns we want for Excel
            excel_df = edited_df[["item_code", "quantity", "final_net_price"]].copy()
            excel_df.columns = ["קוד פריט", "כמות", "מחיר נטו"]

            # Generate Excel in-memory
            import io
            buffer = io.BytesIO()
            excel_df.to_excel(buffer, index=False)
            buffer.seek(0)
            excel_data = buffer.getvalue()
        except Exception as e:
            # Log error but don't crash UI
            logger.error(f"Excel generation preview failed: {e}")

        if excel_data:
            st.download_button(
                label=get_text("btn_download_excel"),  # "הורד אקסל"
                data=excel_data,
                file_name=f"order_{data.get('invoice_number', 'export')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                width="stretch",
            )
        else:
            # Fallback if generation fails (e.g. validation error)
            st.button(
                get_text("btn_download_excel"),
                disabled=True,
                type="primary",
                width="stretch",
                help="Error generating Excel",
            )

    with col2:
        if st.button(get_text("btn_clear_reset"), width="stretch"):
            # Clear session state
            for key in ["extracted_data", "session_metadata", "from_email"]:
                if key in st.session_state:
                    del st.session_state[key]

            # Clear URL query parameters to prevent auto-reload from session ID
            st.query_params.clear()
            st.rerun()

    st.divider()

    # --- New Items Section ---
    # Display new items that were added from this order
    metadata = st.session_state.get("session_metadata", {})
    new_items_data = metadata.get("new_items", [])

    if new_items_data:
        st.subheader(get_text("new_items_section_title"))
        st.caption(get_text("new_items_section_caption"))

        # Prepare display dataframe with Hebrew column names matching the new items Excel
        from src.shared.product_pricing import calculate_sell_price

        new_items_display = []
        for item in new_items_data:
            barcode = str(item.get("barcode", "")).strip() if item.get("barcode") else ""
            final_net_price = item.get("final_net_price", 0) or 0
            sell_price = calculate_sell_price(final_net_price) if final_net_price else 0

            new_items_display.append(
                {
                    "ברקוד": barcode,
                    "שם פריט": item.get("description", ""),
                    "ברקוד 2": barcode,  # Copy of primary
                    "מכירה": sell_price,
                    "עלות נטו": final_net_price,
                    "מספר ספק": supplier_code,
                }
            )

        new_items_df = pd.DataFrame(new_items_display)

        # Display as read-only table
        st.dataframe(new_items_df, width="stretch", hide_index=True)

        # Download button for new items Excel
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

            # Revert Button moved here
            added_barcodes = metadata.get("added_items_barcodes", [])
            if added_barcodes:
                if st.button(
                    get_text("btn_revert_items", count=len(added_barcodes)), type="secondary", width="stretch"
                ):
                    try:
                        items_service = ItemsService()
                        deleted = items_service.delete_items_by_barcodes(added_barcodes)
                        st.success(get_text("msg_revert_success", count=deleted))

                        # Clear from metadata
                        metadata["added_items_barcodes"] = []
                        metadata["new_items"] = []  # Clear table too
                        st.session_state["session_metadata"] = metadata
                        # Update session in DB
                        if session_id:
                            update_session_metadata(session_id, metadata)
                        st.rerun()
                    except Exception as e:
                        st.error(get_text("msg_revert_fail", error=e))

        except Exception as e:
            logger.error(f"New items Excel generation failed: {e}")

    st.divider()

    # --- Retry Extraction Section ---
    with st.container(border=True):
        st.markdown(f"#### {get_text('retry_expander')}")
        st.warning(get_text("retry_warning"))

        # Pre-fill instructions if available
        existing_instructions = ""
        try:
            if supplier_code and supplier_code != "Unknown":
                supplier_service = SupplierService()
                instr = supplier_service.get_supplier_instructions(supplier_code)
                if instr:
                    existing_instructions = instr
        except Exception:
            pass

        custom_instructions = st.text_area(
            get_text("retry_instr_label"),
            value=existing_instructions,
            placeholder=get_text("retry_instr_placeholder"),
            help=get_text("retry_instr_help"),
        )

        if st.button(get_text("btn_retry")):
            metadata = st.session_state.get("session_metadata", {})
            source_uri = metadata.get("source_file_uri")

            if not source_uri:
                st.error(get_text("retry_no_file"))
            else:
                with st.spinner(get_text("retry_spinner")):
                    try:
                        # Download
                        temp_path = "temp_retry_file"
                        # Extract extension from filename for better MIME detection
                        filename = metadata.get("filename", "unknown.pdf")
                        _, ext = os.path.splitext(filename)
                        if ext:
                            temp_path += ext

                        if download_file_from_gcs(source_uri, temp_path):
                            # Init Client (using settings)
                            init_client()

                            # Run Pipeline with explicit instructions
                            from src.core.pipeline import ExtractionPipeline
                            pipeline = ExtractionPipeline()
                            
                            result = pipeline.run_pipeline(
                                file_path=temp_path,
                                mime_type="application/pdf" if not ext else f"application/{ext.lstrip('.')}",
                                force_supplier_instructions=custom_instructions
                            )
                            
                            new_order = result.orders[0] if result.orders else None

                            if new_order:
                                # Update session
                                st.session_state["extracted_data"] = new_order.model_dump()
                                if session_id:
                                    update_session_order(session_id, new_order)

                                st.success(get_text("retry_success"))
                                st.rerun()
                            else:
                                st.error(get_text("phase_extract_fail"))

                            # Cleanup
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        else:
                            st.error(get_text("retry_fail_download"))

                    except Exception as e:
                        st.error(get_text("error_general", error=e))
                        import traceback

                        st.code(traceback.format_exc())
