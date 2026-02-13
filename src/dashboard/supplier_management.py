"""
Super Order Automation - Supplier Management

Streamlit page for viewing, editing, and adding suppliers.
Features: table view, search, edit form, add new supplier form.
"""
import streamlit as st
import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.data.supplier_service import SupplierService
from src.shared.translations import get_text

# Page config
st.set_page_config(page_title="Supplier Management", layout="wide")


def show_supplier_table(suppliers: list, search: str = "", key_version: int = 0):
    """Display suppliers in a searchable table."""
    
    # Filter suppliers based on search
    if search:
        search_lower = search.lower()
        filtered = [
            s for s in suppliers 
            if search_lower in str(s.get('code', '')).lower() 
            or search_lower in str(s.get('name', '')).lower()
            or search_lower in str(s.get('global_id', '')).lower()
            or search_lower in str(s.get('email', '')).lower()
        ]
    else:
        filtered = suppliers
    
    # Convert to DataFrame for display
    df_data = []
    for s in sorted(filtered, key=lambda x: str(x.get('code', ''))):
        df_data.append({
            get_text("sm_th_code"): s.get('code', ''),
            get_text("sm_th_name"): s.get('name', ''),
            get_text("sm_th_global_id"): s.get('global_id', ''),
            get_text("sm_th_phone"): s.get('phone', ''),
            get_text("sm_th_email"): s.get('email', ''),
            get_text("sm_th_instr"): s.get('special_instructions', ''),
        })
    
    df = pd.DataFrame(df_data)
    
    st.markdown(get_text("sm_showing_count", filtered=len(filtered), total=len(suppliers)))
    
    st.info(get_text("sm_table_instr")) # "Click on a row to edit" instruction
    
    # Display table with selection
    key = f"supplier_df_{key_version}"
    event = st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key
    )
    
    # Return selected supplier code
    if event.selection and event.selection.rows:
        selected_idx = event.selection.rows[0]
        if selected_idx < len(filtered):
            return filtered[selected_idx].get('code')
    
    return None


def show_edit_form(supplier_service: SupplierService, supplier_code: str, suppliers: list):
    """Show edit form for a supplier."""
    
    # Find the supplier data
    supplier = next((s for s in suppliers if s.get('code') == supplier_code), None)
    
    if not supplier:
        st.error(get_text("err_not_found", code=supplier_code))
        return
    
    st.subheader(get_text("form_edit_title", code=supplier_code))
    
    with st.form(key=f"edit_form_{supplier_code}"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.text_input(get_text("lbl_code"), value=supplier_code, disabled=True, key=f"edit_code_{supplier_code}")
            name = st.text_input(
                get_text("lbl_name"), 
                value=supplier.get('name', ''),
                key=f"edit_name_{supplier_code}"
            )
            global_id = st.text_input(
                get_text("lbl_global_id") + " *", 
                value=supplier.get('global_id', ''),
                key=f"edit_global_id_{supplier_code}"
            )
        
        with col2:
            email = st.text_input(
                get_text("lbl_email"), 
                value=supplier.get('email', ''),
                key=f"edit_email_{supplier_code}"
            )
            phone = st.text_input(
                get_text("lbl_phone"), 
                value=supplier.get('phone', ''),
                key=f"edit_phone_{supplier_code}"
            )
        
        st.markdown(get_text("lbl_instr_header"))
        st.markdown(get_text("lbl_instr_sub"))
        instructions = st.text_area(
            get_text("retry_instr_label"), # Reuse label "Instructions" or create new
            value=supplier.get('special_instructions', '') or '',
            height=150,
            key=f"edit_instructions_{supplier_code}",
            placeholder=get_text("ph_instr")
        )
        
        col_save, col_cancel = st.columns([1, 4])
        
        with col_save:
            submitted = st.form_submit_button(get_text("btn_save"), type="primary")
        
        with col_cancel:
            cancel = st.form_submit_button(get_text("btn_cancel"))
        
        if submitted:
            if not name or not global_id:
                st.error(get_text("err_req_name_global_id"))
            else:
                success = supplier_service.update_supplier(
                    supplier_code=supplier_code,
                    name=name,
                    global_id=global_id,
                    email=email,
                    phone=phone,
                    special_instructions=instructions
                )
                if success:
                    st.cache_data.clear() # Clear cache on update
                    st.success(get_text("msg_update_success", code=supplier_code))
                    # Clear selection and refresh using key versioning
                    st.session_state['selected_supplier'] = None
                    st.session_state['table_key_version'] += 1
                    st.rerun()
                else:
                    st.error(get_text("err_update_fail"))
        
        if cancel:
            st.session_state['selected_supplier'] = None
            st.session_state['table_key_version'] += 1
            st.rerun()


def show_add_form(supplier_service: SupplierService):
    """Show form to add a new supplier."""
    
    st.subheader(get_text("form_add_title"))
    
    with st.form(key="add_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            code = st.text_input(
                get_text("lbl_code"), 
                key="add_code",
                placeholder=get_text("ph_code")
            )
            name = st.text_input(
                get_text("lbl_name"), 
                key="add_name",
                placeholder=get_text("ph_name")
            )
            global_id = st.text_input(
                get_text("lbl_global_id") + " *", 
                key="add_global_id",
                placeholder=get_text("ph_global_id")
            )
        
        with col2:
            email = st.text_input(
                get_text("lbl_email"), 
                key="add_email",
                placeholder=get_text("ph_email")
            )
            phone = st.text_input(
                get_text("lbl_phone"), 
                key="add_phone",
                placeholder=get_text("ph_phone")
            )
        
        st.markdown(get_text("lbl_instr_header"))
        instructions = st.text_area(
            get_text("retry_instr_label"),
            height=100,
            key="add_instructions",
            placeholder=get_text("ph_instr") # Use same placeholder as edit
        )
        
        col_add, col_cancel = st.columns([1, 4])
        
        with col_add:
            submitted = st.form_submit_button(get_text("btn_add_submit"), type="primary")
        
        with col_cancel:
            cancel = st.form_submit_button(get_text("btn_cancel"))
        
        if submitted:
            if not code or not name or not global_id:
                st.error(get_text("err_req_code_name_global_id"))
            else:
                success = supplier_service.add_supplier(
                    supplier_code=code.strip(),
                    name=name.strip(),
                    global_id=global_id.strip(),
                    email=email.strip() if email else None,
                    phone=phone.strip() if phone else None,
                    special_instructions=instructions.strip() if instructions else None
                )
                if success:
                    st.cache_data.clear() # Clear cache on add
                    st.success(get_text("msg_add_success", code=code))
                    st.session_state['show_add_form'] = False
                    st.rerun()
                else:
                    st.error(get_text("err_add_fail"))
        
        if cancel:
            st.session_state['show_add_form'] = False
            st.rerun()


def main():
    st.title(get_text("sm_title"))
    st.markdown(get_text("sm_subtitle"))
    

    @st.cache_data(ttl=60)
    def get_cached_suppliers(_service):
        return _service.get_all_suppliers()

    # Initialize supplier service
    try:
        supplier_service = SupplierService()
        suppliers = get_cached_suppliers(supplier_service)
    except Exception as e:
        st.error(get_text("sm_conn_fail", error=e))
        st.info(get_text("sm_conn_cred_hint"))
        return
    
    st.success(get_text("sm_conn_success", count=len(suppliers)))
    
    # Initialize session state
    if 'selected_supplier' not in st.session_state:
        st.session_state['selected_supplier'] = None
    if 'show_add_form' not in st.session_state:
        st.session_state['show_add_form'] = False
    if 'table_key_version' not in st.session_state:
        st.session_state['table_key_version'] = 0
    
    # Top bar: Search and Add button
    col_search, col_add = st.columns([4, 1])
    
    with col_search:
        search = st.text_input(
            get_text("sm_search_placeholder"), # Used title as placeholder, or empty key 
            placeholder=get_text("sm_search_placeholder"),
            label_visibility="collapsed"
        )
    
    with col_add:
        if st.button(get_text("btn_add_new"), width="stretch"):
            st.session_state['show_add_form'] = True
            st.session_state['selected_supplier'] = None
            st.session_state['table_key_version'] += 1
            st.rerun()
    
    st.divider()
    
    # Show add form if requested
    if st.session_state.get('show_add_form'):
        show_add_form(supplier_service)
        st.divider()
    
    # Show supplier table or empty state
    if not suppliers:
        st.warning(get_text("sm_no_suppliers"))
        return
    
    # Two column layout: table + edit form
    table_col, form_col = st.columns([2, 3])
    
    with table_col:
        selected_code = show_supplier_table(suppliers, search, st.session_state['table_key_version'])
        
        if selected_code and selected_code != st.session_state.get('selected_supplier'):
            st.session_state['selected_supplier'] = selected_code
            st.session_state['show_add_form'] = False
            st.rerun()
    
    with form_col:
        if st.session_state.get('selected_supplier'):
            show_edit_form(
                supplier_service, 
                st.session_state['selected_supplier'],
                suppliers
            )
        else:
            st.info(get_text("sm_select_hint"))


if __name__ == "__main__":
    main()
