"""
Super Order Automation - Dashboard

Streamlit web UI for viewing and editing extracted order data.
Supports:
- Loading from email session (via ?session=<id> URL parameter)
- Manual file upload via API
"""

import os
import sys
from pathlib import Path

import streamlit as st

# Ensure repository root is importable when running via:
# `streamlit run src/dashboard/app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard import auth, inbox, items_management, order_session, supplier_management  # noqa: E402
from src.shared.config import settings  # noqa: E402
from src.shared.logger import get_logger  # noqa: E402
from src.shared.translations import get_text  # noqa: E402

# Configure logger
logger = get_logger(__name__)

# Verify connection
if not settings.GEMINI_API_KEY and not settings.PROJECT_ID:
    logger.warning("WARNING: Neither GEMINI_API_KEY nor GCP_PROJECT_ID found.")

# Page config
st.set_page_config(page_title="Order-Bot", layout="wide", initial_sidebar_state="auto")


# Load external CSS globally BEFORE authentication stops the script
def load_css(file_path):
    with open(file_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def render_primary_navigation() -> None:
    """Render primary navigation in the main content area."""
    nav_items = [
        (get_text("nav_inbox"), "inbox"),
        (get_text("nav_upload"), "upload"),
        (get_text("nav_suppliers"), "suppliers"),
        (get_text("nav_items"), "items"),
    ]

    with st.container(border=True):
        st.caption(get_text("nav_title"))

        if "user_email" in st.session_state:
            user_col, logout_col = st.columns([4, 1])
            with user_col:
                st.caption(get_text("auth_logged_in_as", email=st.session_state["user_email"]))
            with logout_col:
                if st.button(get_text("auth_btn_logout"), width="stretch", key="top_nav_logout"):
                    auth.logout()

        nav_columns = st.columns(len(nav_items))
        for column, (label, page_name) in zip(nav_columns, nav_items, strict=False):
            with column:
                is_current_page = st.session_state.get("page", "inbox") == page_name
                if st.button(
                    label,
                    width="stretch",
                    type="primary" if is_current_page else "secondary",
                    key=f"top_nav_{page_name}",
                ):
                    st.session_state["page"] = page_name
                    st.rerun()

        if settings.GEMINI_API_KEY or settings.PROJECT_ID:
            st.success("AI מחובר למערכת ✅")
        else:
            st.error("מפתח AI חסר ❌")


css_path = os.path.join(os.path.dirname(__file__), "styles.css")
load_css(css_path)

# --- Authentication ---
auth.require_login()

# --- Session Loading Logic ---
query_params = st.query_params
order_id = query_params.get("order_id")
if isinstance(order_id, list):
    order_id = order_id[0] if order_id else None

# Check for legacy session links
legacy_session = query_params.get("session")
if legacy_session:
    st.error(get_text("session_expired") + " (Legacy link replaced by permanent order links)")
    st.stop()

if not order_id:
    order_id = st.session_state.get("active_order_id")

# Load from ?order_id= URL param (inbox link / direct link)
if order_id and "extracted_data" not in st.session_state:
    from src.data.orders_service import OrdersService  # noqa: PLC0415

    try:
        order_doc = OrdersService().get_order(order_id)
    except Exception as e:
        order_doc = None
        st.error(get_text("error_general", error=e))

    if order_doc:
        metadata = {
            "filename": order_doc.get("ui_metadata", {}).get("filename", order_doc.get("filename")),
            "subject": order_doc.get("ui_metadata", {}).get("subject", order_doc.get("subject")),
            "sender": order_doc.get("ui_metadata", {}).get("sender", order_doc.get("sender")),
            "source_file_uri": order_doc.get("gcs_uri"),
            "is_test": bool(order_doc.get("is_test", False)),
            "from_orders_inbox": True,
        }
        st.session_state["extracted_data"] = order_doc
        st.session_state["session_metadata"] = metadata
        st.session_state["from_email"] = True
        st.session_state["active_order_id"] = order_id
        # Route directly to order session view
        st.session_state["page"] = "order_session"
    else:
        st.error(get_text("session_expired"))

# --- Navigation ---
# Default to inbox (not dashboard) when no order is loaded
if "page" not in st.session_state:
    st.session_state["page"] = "inbox"

render_primary_navigation()

# --- Page Routing ---
current_page = st.session_state.get("page", "inbox")

if current_page == "suppliers":
    supplier_management.main()
    st.stop()

if current_page == "items":
    items_management.render_items_management_page()
    st.stop()

if current_page == "order_session":
    st.title(get_text("dashboard_title"))
    order_session.render_order_session()
    st.stop()

if current_page == "inbox":
    st.title(get_text("dashboard_title"))
    inbox.render_orders_inbox(show_title=True, embedded=False)
    st.stop()

# --- Upload / Manual Extraction Page ---
if current_page == "upload":
    from src.data.orders_service import OrdersService  # noqa: PLC0415
    from src.extraction.vertex_client import init_client  # noqa: PLC0415
    from src.ingestion.firestore_writer import save_order_to_firestore  # noqa: PLC0415
    from src.ingestion.gcs_writer import upload_to_gcs  # noqa: PLC0415

    st.title(get_text("dashboard_title"))
    st.markdown(get_text("dashboard_intro_no_email"))

    selected_order_type = st.radio(
        get_text("order_type_label"),
        options=[False, True],
        format_func=lambda val: get_text("order_type_test") if val else get_text("order_type_real"),
        horizontal=True,
    )
    uploaded_file = st.file_uploader(get_text("upload_label"), type=["pdf", "xlsx", "xls"])

    if uploaded_file is not None:
        if st.button(get_text("btn_extract"), type="primary", width="stretch"):
            with st.spinner(get_text("spinner_processing")):
                try:
                    temp_path = f"acc_{uploaded_file.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    if uploaded_file.name.lower().endswith(".xlsx"):
                        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    elif uploaded_file.name.lower().endswith(".xls"):
                        mime_type = "application/vnd.ms-excel"
                    else:
                        mime_type = "application/pdf"

                    init_client()

                    from src.core.pipeline import ExtractionPipeline  # noqa: PLC0415

                    pipeline = ExtractionPipeline()
                    result = pipeline.run_pipeline(
                        file_path=temp_path,
                        mime_type=mime_type,
                        email_metadata={"body": "Attached is the invoice."},
                    )
                    order = result.orders[0] if result.orders else None

                    if result.supplier_code != "UNKNOWN":
                        st.info(get_text("phase_1_identified", name=result.supplier_name, code=result.supplier_code))
                    else:
                        st.warning(get_text("phase_1_unknown"))

                    if order:
                        order.is_test = bool(selected_order_type)
                        if result.detection_method == "extraction_fallback":
                            st.success(get_text("phase_fallback_success", code=result.supplier_code))

                        if result.new_items_added > 0:
                            st.info(get_text("new_items_found", count=len(result.new_items_data)))
                            st.success(get_text("new_items_added", count=result.new_items_added))

                        try:
                            source_uri = upload_to_gcs(temp_path, uploaded_file.name)
                        except Exception as e:
                            st.warning(get_text("gcs_upload_fail", error=e))
                            source_uri = None

                        # Save the manually extracted order to Firestore directly
                        order_metadata = {
                            "filename": uploaded_file.name,
                            "phase1_reasoning": result.phase1_reasoning,
                            "from_manual_upload": True,
                        }

                        doc_id = save_order_to_firestore(
                            order,
                            source_file_uri=source_uri or "",
                            is_test=bool(selected_order_type),
                            metadata=order_metadata,
                            new_items_data=result.new_items_data,
                            added_items_barcodes=result.added_barcodes,
                        )

                        if not doc_id:
                            st.error("שגיאה בשמירת ההזמנה למסד הנתונים")
                            st.stop()

                        # Read it back to match the structure that order_session expects
                        saved_order = OrdersService().get_order(doc_id)
                        st.session_state["extracted_data"] = saved_order
                        st.session_state["session_metadata"] = {
                            "filename": uploaded_file.name,
                            "source_file_uri": source_uri,
                            "is_test": bool(selected_order_type),
                            "from_orders_inbox": False,
                            "from_manual_upload": True,
                        }
                        st.session_state["from_email"] = False
                        st.session_state["active_order_id"] = doc_id
                        st.session_state["page"] = "order_session"

                        if os.path.exists(temp_path):
                            os.remove(temp_path)

                        st.rerun()
                    else:
                        st.error(get_text("phase_extract_fail"))

                except Exception as e:
                    st.error(get_text("error_general", error=e))
                    import traceback

                    st.code(traceback.format_exc())
