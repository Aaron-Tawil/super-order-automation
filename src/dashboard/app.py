"""
Super Order Automation - Dashboard

Streamlit web UI for viewing and editing extracted order data.
Supports:
- Loading from email session (via ?session=<id> URL parameter)
- Manual file upload via API
"""
import streamlit as st
import pandas as pd
import requests
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.export.excel_generator import generate_excel_from_order
from src.shared.models import ExtractedOrder, LineItem
from src.shared.session_store import get_session, update_session_order, update_session_metadata
from src.data.items_service import ItemsService
from src.data.supplier_service import SupplierService
from src.extraction.vertex_client import init_client, process_invoice, detect_supplier
from src.ingestion.gcs_writer import download_file_from_gcs, upload_to_gcs
from src.dashboard import supplier_management
from src.dashboard import items_management
from src.shared.translations import get_text
from dotenv import load_dotenv, find_dotenv

# Load env vars
# Force find .env file
env_file = find_dotenv(usecwd=True)
load_dotenv(env_file, override=True)

API_KEY = os.getenv("GEMINI_API_KEY")
PROJECT_ID = os.getenv("GCP_PROJECT_ID")

# Verify connection
if not API_KEY and not PROJECT_ID:
    print("WARNING: Neither GEMINI_API_KEY nor GCP_PROJECT_ID found.")

# Page config
# Page config
st.set_page_config(page_title=get_text("dashboard_title"), layout="wide", initial_sidebar_state="expanded")

# Inject RTL CSS
st.markdown("""
    <style>
    body {
        direction: rtl;
        text-align: right;
    }
    .stApp {
        direction: rtl;
    }
    /* Align Streamlit widgets to right */
    .stTextInput > label, .stSelectbox > label, .stNumberInput > label, .stTextArea > label, .stFileUploader > label {
        text-align: right;
        width: 100%;
        display: block;
        float: right;
    }
    /* Force headers and markdown to right align */
    h1, h2, h3, h4, h5, h6, .stMarkdown, .stText, p {
        text-align: right !important;
    }
    /* Fix for metrics label */
    [data-testid="stMetricLabel"] {
        justify-content: flex-end;
    }
    /* Metrics alignment - handled above */
    [data-testid="stMetricValue"] {
        justify-content: right;
    }
    /* Sidebar alignment (tricky in pure CSS but we try) */
    [data-testid="stSidebar"] {
        direction: rtl; 
        text-align: right;
    }
    /* Toast/Alert alignment */
    .stAlert {
        direction: rtl;
        text-align: right;
    }
    /* Button alignment in columns */
    .stButton button {
        float: right;
    }
    
    /* Hide the 'Deploy' button and hamburger menu */
    .stAppDeployButton {
        display: none;
    }
    
    /* Hide sidebar collapse button - Force with !important and multiple selectors */
    [data-testid="stSidebarCollapsedControl"], section[data-testid="stSidebar"] > div > div:first-child button {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Session Loading Logic ---
# Check for session token in URL (from email link)
query_params = st.query_params
session_id = query_params.get("session")

if session_id and 'extracted_data' not in st.session_state:
    session = get_session(session_id)
    if session:
        # Load order data from session (already a dict from JSON file)
        order = session["order"]
        metadata = session.get("metadata", {})
        
        # order is already a dict (loaded from JSON file)
        st.session_state['extracted_data'] = order
        st.session_state['session_metadata'] = metadata
        st.session_state['from_email'] = True
        st.success(get_text("dashboard_intro_email", filename=metadata.get('subject', 'Unknown')))
    else:
        st.error(get_text("session_expired"))

# --- Navigation ---
if 'page' not in st.session_state:
    st.session_state['page'] = 'dashboard'

# Sidebar for navigation
with st.sidebar:
    st.title(get_text("nav_title"))
    if st.button(get_text("nav_dashboard"), width="stretch"):
        st.session_state['page'] = 'dashboard'
        st.rerun()
    
    if st.button(get_text("nav_suppliers"), width="stretch"):
        st.session_state['page'] = 'suppliers'
        st.rerun()

    if st.button(get_text("nav_items"), width="stretch"):
        st.session_state['page'] = 'items'
        st.rerun()

    st.divider()
    # Debug Info
    if API_KEY:
        st.sidebar.success("AI מחובר למערכת ✅") # More meaningful text
    else:
        st.sidebar.error("מפתח AI חסר ❌")

# --- Page Routing ---
if st.session_state['page'] == 'suppliers':
    supplier_management.main()
    st.stop()  # Stop execution here for this page

if st.session_state['page'] == 'items':
    items_management.render_items_management_page()
    st.stop()


# --- Dashboard Logic ---
# --- Header ---
st.title(get_text("dashboard_title"))

# Show different intro based on source
if st.session_state.get('from_email'):
    metadata = st.session_state.get('session_metadata', {})
    st.info(get_text("dashboard_intro_email", filename=metadata.get('filename', 'email')))
else:
    st.markdown(get_text("dashboard_intro_no_email"))

# Validation Warnings
if 'extracted_data' in st.session_state:
    order_data = st.session_state['extracted_data']
    if order_data.get('warnings'):
        for w in order_data['warnings']:
            st.error(w)

# --- File Upload Section (only show if not from email) ---
if not st.session_state.get('from_email'):
    uploaded_file = st.file_uploader(get_text("upload_label"), type=["pdf", "xlsx"])

    if uploaded_file is not None:
        if st.button(get_text("btn_extract"), type="primary", width="stretch"):
            with st.spinner(get_text("spinner_processing")):
                try:
                    # 1. Save to Temp
                    temp_path = f"acc_{uploaded_file.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    # Determine MIME type
                    if uploaded_file.name.lower().endswith('.xlsx'):
                        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    else:
                        mime_type = "application/pdf"
                        
                    # Init Services
                    init_client(api_key=API_KEY, project_id=PROJECT_ID)
                    supplier_service = SupplierService()
                    items_service = ItemsService()
                    
                    # 2. Phase 1: Supplier Detection
                    st.text(get_text("phase_1_detect"))
                    detected_code, confidence = detect_supplier(
                        email_body="", # No email context for manual upload
                        invoice_file_path=temp_path,
                        invoice_mime_type=mime_type
                    )
                    
                    supplier_instructions = None
                    if detected_code != "UNKNOWN":
                        # Validate existence
                        s_data = supplier_service.get_supplier(detected_code)
                        if s_data:
                            st.info(get_text("phase_1_identified", name=s_data.get('name'), code=detected_code))
                            supplier_instructions = s_data.get('special_instructions')
                        else:
                            detected_code = "UNKNOWN"
                    
                    if detected_code == "UNKNOWN":
                        st.warning(get_text("phase_1_unknown"))

                    # 3. Phase 2: Extraction
                    st.text(get_text("phase_2_extract"))
                    order = process_invoice(
                        temp_path,
                        mime_type=mime_type,
                        supplier_instructions=supplier_instructions
                    )
                    
                    if order:
                        # Fallback matching if needed
                        if detected_code == "UNKNOWN" or confidence < 0.7:
                            fallback = supplier_service.match_supplier(
                                global_id=order.supplier_global_id,
                                email=order.supplier_email,
                                phone=order.supplier_phone
                            )
                            if fallback != "UNKNOWN":
                                detected_code = fallback
                                st.success(get_text("phase_fallback_success", code=detected_code))
                        
                        # Set supplier in order
                        order.supplier_code = detected_code
                        s_data = supplier_service.get_supplier(detected_code)
                        order.supplier_name = s_data.get('name', 'Unknown') if s_data else 'Unknown'
                        
                        # 4. New Items Detection
                        st.text(get_text("new_items_checking"))
                        added_barcodes = []
                        new_items_data = []  # For dashboard display
                        try:
                            all_barcodes = [str(i.barcode).strip() for i in order.line_items if i.barcode]
                            valid_barcodes = [b for b in all_barcodes if len(b) >= 11]
                            
                            new_barcodes = items_service.get_new_barcodes(valid_barcodes)
                            
                            if new_barcodes:
                                st.info(get_text("new_items_found", count=len(new_barcodes)))
                                # Filter items to add
                                items_to_add = []
                                seen = set()
                                for item in order.line_items:
                                    if item.barcode in new_barcodes and item.barcode not in seen:
                                        # User requested to set item_code same as barcode for auto-added items
                                        items_to_add.append({
                                            "barcode": item.barcode, 
                                            "name": item.description,
                                            "item_code": item.barcode 
                                        })
                                        # Collect new items data for dashboard display
                                        new_items_data.append({
                                            "barcode": str(item.barcode) if item.barcode else "",
                                            "description": item.description,
                                            "final_net_price": item.final_net_price or 0
                                        })
                                        seen.add(item.barcode)
                                
                                added = items_service.add_new_items_batch(items_to_add)
                                added_barcodes = [i['barcode'] for i in items_to_add]
                                st.success(get_text("new_items_added", count=added))
                        except Exception as e:
                            st.error(get_text("error_general", error=e))

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
                            "added_items_barcodes": added_barcodes,
                            "new_items": new_items_data,  # For dashboard new items section
                            "from_manual_upload": True
                        }
                        
                        st.session_state['extracted_data'] = order.model_dump()
                        st.session_state['session_metadata'] = session_metadata
                        st.session_state['from_email'] = False # It is manual, but we treat it as loaded now
                        
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
if 'extracted_data' in st.session_state:
    data = st.session_state['extracted_data']
    
    st.divider()
    
    # Header Info
    c1, c2 = st.columns(2)
    
    # Use supplier info from order object if available
    supplier_name = data.get('supplier_name') or 'Unknown'
    supplier_code = data.get('supplier_code') or 'Unknown'
    
    c1.metric(get_text("metric_supplier"), f"{supplier_name} ({supplier_code})")
    c2.metric(get_text("metric_invoice"), data.get('invoice_number', 'Unknown'))
    
    # Line Items Editor
    st.subheader(get_text("editor_title"))
    st.caption(get_text("editor_caption"))
    
    # Create a display dataframe with only the columns shown in the output Excel
    # The Excel has: קוד פריט (item_code), כמות (quantity), מחיר נטו (final_net_price)
    items_service = ItemsService()
    display_data = []
    
    # Batch lookup for all barcodes
    all_barcodes = [str(item.get('barcode', '')).strip() for item in data['line_items'] if item.get('barcode')]
    items_map = {} # Map barcode -> db_item_code
    
    if all_barcodes:
        db_items = items_service.get_items_batch(all_barcodes)
        for db_item in db_items:
            b = str(db_item.get('barcode'))
            code = db_item.get('item_code')
            if b and code:
                items_map[b] = code

    for item in data['line_items']:
        barcode = str(item.get('barcode', '')).strip() if item.get('barcode') else ""
        item_code_val = barcode  # Default to barcode
        
        # Use batched lookup result
        if barcode in items_map:
            item_code_val = items_map[barcode]
        elif barcode.startswith('0') and barcode.lstrip('0') in items_map:
            item_code_val = items_map[barcode.lstrip('0')]
        
        display_data.append({
            'item_code': item_code_val,
            'description': item.get('description', ''),
            'quantity': item.get('quantity', 0),
            'final_net_price': item.get('final_net_price', 0),
            # Keep barcode hidden for Excel generation
            '_barcode': barcode
        })
    
    df = pd.DataFrame(display_data)
    
    # Only show user-facing columns (not internal _barcode)
    display_cols = ['item_code', 'description', 'quantity', 'final_net_price']
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
        }
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
            excel_df = edited_df[['item_code', 'quantity', 'final_net_price']].copy()
            excel_df.columns = ['קוד פריט', 'כמות', 'מחיר נטו']
            
            # Generate Excel
            output_path = f"temp_order_{data.get('invoice_number', 'gen')}.xlsx"
            excel_df.to_excel(output_path, index=False)
            
            with open(output_path, "rb") as f:
                excel_data = f.read()
            
            # Cleanup
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception as e:
            # Log error but don't crash UI, button will be disabled or show error logic
            print(f"Excel generation preview failed: {e}")

        if excel_data:
            st.download_button(
                label=get_text("btn_download_excel"), # "הורד אקסל"
                data=excel_data,
                file_name=f"order_{data.get('invoice_number', 'export')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                width="stretch"
            )
        else:
            # Fallback if generation fails (e.g. validation error)
            st.button(get_text("btn_download_excel"), disabled=True, type="primary", width="stretch", help="Error generating Excel")
    
    with col2:
        if st.button(get_text("btn_clear_reset"), width="stretch"):
            # Clear session state
            for key in ['extracted_data', 'session_metadata', 'from_email']:
                if key in st.session_state:
                    del st.session_state[key]
            
            # Clear URL query parameters to prevent auto-reload from session ID
            st.query_params.clear()
            st.rerun()

    st.divider()
    
    # --- New Items Section ---
    # Display new items that were added from this order
    metadata = st.session_state.get('session_metadata', {})
    new_items_data = metadata.get('new_items', [])
    
    if new_items_data:
        st.subheader(get_text("new_items_section_title"))
        st.caption(get_text("new_items_section_caption"))
        
        # Prepare display dataframe with Hebrew column names matching the new items Excel
        from src.shared.price_utils import calculate_sell_price
        
        new_items_display = []
        for item in new_items_data:
            barcode = str(item.get('barcode', '')).strip() if item.get('barcode') else ""
            final_net_price = item.get('final_net_price', 0) or 0
            sell_price = calculate_sell_price(final_net_price) if final_net_price else 0
            
            new_items_display.append({
                'ברקוד': barcode,
                'שם פריט': item.get('description', ''),
                'ברקוד 2': barcode,  # Copy of primary
                'מכירה': sell_price,
                'עלות נטו': final_net_price,
                'מספר ספק': supplier_code,
            })
        
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
                width="stretch"
            )
            
            # Revert Button moved here
            added_barcodes = metadata.get('added_items_barcodes', [])
            if added_barcodes:
                if st.button(get_text("btn_revert_items", count=len(added_barcodes)), type="secondary", width="stretch"):
                    try:
                        items_service = ItemsService()
                        deleted = items_service.delete_items_by_barcodes(added_barcodes)
                        st.success(get_text("msg_revert_success", count=deleted))
                        
                        # Clear from metadata
                        metadata['added_items_barcodes'] = []
                        metadata['new_items'] = [] # Clear table too
                        st.session_state['session_metadata'] = metadata
                        # Update session in DB
                        if session_id:
                             update_session_metadata(session_id, metadata)
                        st.rerun()
                    except Exception as e:
                        st.error(get_text("msg_revert_fail", error=e))

        except Exception as e:
            print(f"New items Excel generation failed: {e}")
    
    st.divider()
    
    # --- Retry Extraction Section ---
    with st.container(border=True):
        st.markdown(f"#### {get_text('retry_expander')}")
        st.warning(get_text("retry_warning"))
        
        # Pre-fill instructions if available
        existing_instructions = ""
        try:
             if supplier_code and supplier_code != 'Unknown':
                 supplier_service = SupplierService()
                 instr = supplier_service.get_supplier_instructions(supplier_code)
                 if instr:
                     existing_instructions = instr
        except:
            pass
            
        custom_instructions = st.text_area(
            get_text("retry_instr_label"),
            value=existing_instructions,
            placeholder=get_text("retry_instr_placeholder"),
            help=get_text("retry_instr_help")
        )
        
        if st.button(get_text("btn_retry")):
            metadata = st.session_state.get('session_metadata', {})
            source_uri = metadata.get('source_file_uri')
            
            if not source_uri:
                st.error(get_text("retry_no_file"))
            else:
                with st.spinner(get_text("retry_spinner")):
                    try:
                        # Download
                        temp_path = "temp_retry_file"
                        # Extract extension from filename for better MIME detection
                        filename = metadata.get('filename', 'unknown.pdf')
                        _, ext = os.path.splitext(filename)
                        if ext:
                            temp_path += ext
                            
                        if download_file_from_gcs(source_uri, temp_path):
                            # Init Client
                            init_client(api_key=API_KEY, project_id=PROJECT_ID)
                            
                            # Supplier Service
                            supplier_service = SupplierService()
                            
                            # Update instructions if provided
                            if custom_instructions and supplier_code and supplier_code != 'UNKNOWN':
                                supplier_service.update_supplier(
                                    supplier_code=supplier_code, 
                                    special_instructions=custom_instructions
                                )
                                st.info(get_text("retry_instr_updated", code=supplier_code))
                                
                            # Re-process
                            new_order = process_invoice(
                                temp_path, 
                                supplier_instructions=custom_instructions
                            )
                            
                            if new_order:
                                # Preserve supplier info
                                new_order.supplier_name = supplier_name
                                new_order.supplier_code = supplier_code
                                
                                # Update session
                                st.session_state['extracted_data'] = new_order.model_dump()
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
