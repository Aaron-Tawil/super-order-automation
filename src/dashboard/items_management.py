import streamlit as st
import pandas as pd
from typing import Optional
import logging
from io import BytesIO
from src.data.items_service import ItemsService
from src.shared.translations import get_text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _clean_numeric_str(val) -> Optional[str]:
    """Helper to remove .0 from float-like strings"""
    if val is None:
        return None
    s = str(val).strip()
    if s == 'nan' or s == 'None':
        return None
    if s.endswith('.0'):
        return s[:-2]
    return s

def render_items_management_page():
    items_service = ItemsService()
    
    # Get total count for display
    try:
        total_items = items_service.get_total_items_count()
        header_text = get_text("im_header_total_count", count=total_items)
    except Exception as e:
        logger.error(f"Failed to get item count: {e}")
        header_text = get_text("im_title")

    st.header(header_text)
    
    # --- Tabbed Interface ---
    tab1, tab3, tab4, tab2 = st.tabs([get_text("im_tab_search"), get_text("im_tab_add"), get_text("im_tab_delete"), get_text("im_tab_reset")])
    
    # --- Tab 1: Search & Edit ---
    with tab1:
        st.subheader(get_text("im_tab_search"))
        # Stacked layout: Input then Button
        search_query_input = st.text_input(get_text("im_search_label"), placeholder=get_text("im_search_placeholder"))
        search_clicked = st.button("חפש", type="primary", key="btn_search_main")
        
        search_query = search_query_input if search_query_input else ""
        
        # Check for success message from previous run
        if 'item_updated_msg' in st.session_state:
            st.success(st.session_state['item_updated_msg'])
            del st.session_state['item_updated_msg']
        
        if search_query and (search_clicked or search_query):
            results = items_service.search_items(search_query)
            if results:
                st.write(get_text("im_found_count", count=len(results)))
                
                # Display as dataframe
                df_results = pd.DataFrame(results)
                # Reorder columns
                cols = ['barcode', 'name', 'item_code', 'note']
                # Ensure all cols exist
                for c in cols:
                    if c not in df_results.columns:
                        df_results[c] = None
                
                # Clean up display values
                if 'barcode' in df_results.columns:
                    df_results['barcode'] = df_results['barcode'].apply(_clean_numeric_str)
                if 'item_code' in df_results.columns:
                    df_results['item_code'] = df_results['item_code'].apply(_clean_numeric_str)

                st.dataframe(df_results[cols], hide_index=True, width="stretch")
                
                # Edit First Match (Simplification for now)
                if len(results) == 1:
                    item = results[0]
                    st.divider()
                    st.subheader(get_text("im_edit_title", name=item.get('name')))
                    
                    # Clean values for the form
                    current_code = _clean_numeric_str(item.get('item_code', '')) or ''
                    current_barcode = _clean_numeric_str(item.get('barcode', ''))
                    
                    with st.form("edit_item_form"):
                         new_name = st.text_input(get_text("lbl_name"), value=item.get('name', ''))
                         new_code = st.text_input("קוד פריט", value=current_code)
                         new_note = st.text_input("הערה", value=item.get('note', ''))
                         
                         submitted = st.form_submit_button(get_text("im_btn_update"))
                         if submitted:
                             if items_service.update_item(current_barcode, new_name, new_code, new_note):
                                 st.session_state['item_updated_msg'] = get_text("im_msg_update_success")
                                 st.rerun()
                             else:
                                 st.error(get_text("im_msg_update_fail"))
            else:
                st.info(get_text("im_no_results"))

    # --- Tab 3: Add Items (Manual & Batch) ---
    with tab3:
        st.subheader(get_text("im_add_manual_title"))
        with st.form("add_item_manual"):
            col1, col2 = st.columns(2)
            with col1:
                new_barcode = st.text_input("ברקוד *")
                new_item_code = st.text_input("קוד פריט *")
            with col2:
                new_name = st.text_input(get_text("lbl_name") + " *")
                new_note = st.text_input("הערה")
            
            submitted_add = st.form_submit_button(get_text("im_btn_add_item"))
            if submitted_add:
                if not new_barcode or not new_name or not new_item_code:
                     st.error("ברקוד, שם וקוד פריט הם שדות חובה.")
                else:
                    if items_service.barcode_exists(new_barcode):
                        st.error(get_text("im_msg_add_fail"))
                    else:
                        if items_service.add_new_item(new_barcode, new_name, new_item_code, new_note):
                            st.success(get_text("im_msg_add_success", name=new_name))
                        else:
                            st.error(get_text("im_msg_add_fail"))

        st.divider()
        st.subheader(get_text("im_add_batch_title"))
        st.markdown(get_text("im_sample_desc"))
        
        # Download Sample Logic
        sample_items = items_service.get_random_items(2)
        sample_data = []
        for item in sample_items:
             sample_data.append({
                 'ברקוד': _clean_numeric_str(item.get('barcode', '')),
                 'שם': item.get('name', ''),
                 'קוד פריט': _clean_numeric_str(item.get('item_code', '')),
                 'הערה': item.get('note', '')
             })
        
        if not sample_data:
            df_sample = pd.DataFrame(columns=['ברקוד', 'שם', 'קוד פריט', 'הערה'])
        else:
            df_sample = pd.DataFrame(sample_data)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_sample.to_excel(writer, index=False)
        excel_data = output.getvalue()
        
        st.download_button(
            label=get_text("im_download_sample"),
            data=excel_data,
            file_name="items_sample.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        batch_file = st.file_uploader(get_text("im_batch_upload_label"), type=['xlsx'], key="batch_add")
        if batch_file:
            try:
                df_batch = pd.read_excel(batch_file)
                # Check optional cols
                items_to_add = []
                for _, row in df_batch.iterrows():
                    barcode = _clean_numeric_str(row.get('ברקוד'))
                    name = str(row.get('שם', '')).strip()
                    item_code = _clean_numeric_str(row.get('קוד פריט'))
                    if not item_code:
                        item_code = _clean_numeric_str(row.get('פריט')) # Fallback
                    note = str(row.get('הערה', '')).strip() if pd.notna(row.get('הערה')) else None
                    
                    if barcode and name and item_code and barcode != 'nan' and name != 'nan':
                        items_to_add.append({
                            'barcode': barcode,
                            'name': name,
                            'item_code': item_code,
                            'note': note
                        })
                
                if items_to_add:
                    st.write(f"נמצאו {len(items_to_add)} פריטים תקינים בקובץ.")
                    if st.button("הוסף פריטים למערכת"):
                         with st.status("מעבד...", expanded=True):
                             added = items_service.add_new_items_batch(items_to_add)
                             st.success(get_text("im_batch_success", count=added))
                else:
                    st.warning("לא נמצאו פריטים תקינים או שחסרים שדות חובה (ברקוד, שם, קוד פריט).")
                    
            except Exception as e:
                st.error(f"Error: {e}")

    # --- Tab 4: Delete Items ---
    with tab4:
        st.subheader(get_text("im_del_manual_title"))
        
        # Check for success message from previous run
        if 'item_deleted_msg' in st.session_state:
            st.success(st.session_state['item_deleted_msg'])
            del st.session_state['item_deleted_msg']
        
        del_query_input = st.text_input(get_text("im_del_lookup_label"))
        del_clicked = st.button("חפש", type="primary", key="btn_search_del")
        
        del_query = del_query_input if del_query_input else ""
        
        if del_query and (del_clicked or del_query):
            del_results = items_service.search_items(del_query)
            if del_results:
                # Just show the first match for simplicity in this flow
                to_delete = del_results[0]
                st.info(f"נמצא: {to_delete.get('name')} ({to_delete.get('barcode')})")
                
                if st.button(get_text("im_btn_delete"), type="primary", key="del_single_btn"):
                    if items_service.delete_items_by_barcodes([to_delete['barcode']]) > 0:
                        st.session_state['item_deleted_msg'] = get_text("im_msg_del_success", name=to_delete.get('name'))
                        st.rerun()
                    else:
                         st.error(get_text("im_msg_del_fail"))
            else:
                 st.warning(get_text("im_no_results"))
                 
        st.divider()
        st.subheader(get_text("im_del_batch_title"))
        st.markdown(get_text("im_del_sample_desc"))
        
        # Download Delete Sample Logic
        del_sample_items = items_service.get_random_items(2)
        del_sample_data = []
        for item in del_sample_items:
             del_sample_data.append({
                 'ברקוד': _clean_numeric_str(item.get('barcode', ''))
             })
        
        if not del_sample_data:
            df_del_sample = pd.DataFrame(columns=['ברקוד'])
        else:
            df_del_sample = pd.DataFrame(del_sample_data)
            
        output_del = BytesIO()
        with pd.ExcelWriter(output_del, engine='openpyxl') as writer:
            df_del_sample.to_excel(writer, index=False)
        excel_data_del = output_del.getvalue()
        
        st.download_button(
            label=get_text("im_del_btn_sample"),
            data=excel_data_del,
            file_name="items_delete_sample.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_dl_del_sample"
        )
        
        del_batch_file = st.file_uploader(get_text("im_del_upload_label"), type=['xlsx'], key="batch_del")
        if del_batch_file:
            try:
                df_del_batch = pd.read_excel(del_batch_file)
                barcodes_to_del = []
                for _, row in df_del_batch.iterrows():
                    # Support 'ברקוד' or just first column if headers match
                    if 'ברקוד' in row:
                        b = _clean_numeric_str(row['ברקוד'])
                        if b:
                            barcodes_to_del.append(b)
                    
                if barcodes_to_del:
                    st.write(f"נמצאו {len(barcodes_to_del)} ברקודים למחיקה.")
                    if st.button("מחק פריטים אלו", type="primary"):
                        with st.status("מוחק...", expanded=True):
                            deleted_count = items_service.delete_items_by_barcodes(barcodes_to_del)
                            st.success(get_text("im_del_batch_success", count=deleted_count))
                else:
                    st.warning("לא נמצאו ברקודים תקינים בקובץ (ודא כותרת 'ברקוד').")
            except Exception as e:
                 st.error(f"Error: {e}")

    # --- Tab 2: Reset Database ---
    with tab2:
        st.subheader("⚠️ Dangerous Area") # Keep English/Icon standard or translate
        st.warning(get_text("im_reset_warning"))
        
        st.markdown(get_text("im_reset_desc"))
        
        uploaded_file = st.file_uploader(get_text("im_upload_label"), type=['xlsx'])
        
        if uploaded_file:
            # Inspection
            try:
                # Preview
                df_preview = pd.read_excel(uploaded_file, header=1) # Assuming header is on 2nd row as seen before
                
                # Clean preview for display
                for col in ['ברקוד', 'פריט']:
                    if col in df_preview.columns:
                        df_preview[col] = df_preview[col].apply(lambda x: _clean_numeric_str(x) if pd.notna(x) else x)

                st.write(get_text("im_preview_title"))
                st.dataframe(df_preview.head())
                
                # Validate columns
                required_cols = ['ברקוד', 'שם'] # Hebrew headers based on user's file
                missing_cols = [c for c in required_cols if c not in df_preview.columns]
                
                if missing_cols:
                    st.error(get_text("im_err_missing_cols", cols=', '.join(missing_cols)))
                else:
                    st.divider()
                    confirm = st.checkbox(get_text("im_confirm_checkbox"))
                    
                    if st.button(get_text("im_btn_replace"), type="primary", disabled=not confirm):
                        if not confirm:
                            st.error(get_text("im_err_confirm"))
                        else:
                            with st.status(get_text("im_status_processing"), expanded=True) as status:
                                # 1. Delete All
                                status.write(get_text("im_status_deleting"))
                                deleted_count = items_service.delete_all_items()
                                status.write(get_text("im_status_deleted", count=deleted_count))
                                
                                # 2. Process Excel
                                status.write(get_text("im_status_reading"))
                                items_to_add = []
                                
                                # Iterate rows
                                for _, row in df_preview.iterrows():
                                    barcode = _clean_numeric_str(row.get('ברקוד'))
                                    name = str(row['שם']).strip()
                                    
                                    # Skip invalid rows
                                    if not barcode or barcode.lower() == 'nan':
                                        continue
                                        
                                    item_code = _clean_numeric_str(row.get('פריט'))
                                    note = str(row['הערה']).strip() if 'הערה' in row and not pd.isna(row['הערה']) else None
                                    
                                    items_to_add.append({
                                        'barcode': barcode,
                                        'name': name,
                                        'item_code': item_code,
                                        'note': note
                                    })
                                
                                status.write(get_text("im_status_found_valid", count=len(items_to_add)))
                                
                                # 3. Add in Batches
                                status.write(get_text("im_status_uploading"))
                                added_count = items_service.add_new_items_batch(items_to_add)
                                
                                status.write(get_text("im_status_success_batched", count=added_count))
                                status.update(label=get_text("im_status_complete"), state="complete")
                                
                            st.success(get_text("im_msg_reset_success", old=deleted_count, new=added_count))
                            
            except Exception as e:
                st.error(get_text("im_err_read_file", error=e))

