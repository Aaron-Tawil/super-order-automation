"""
Read-only failed processing event detail page.
"""

from __future__ import annotations

import os

import streamlit as st

from src.data.processing_events_service import ProcessingEventsService
from src.data.supplier_service import SupplierService
from src.ingestion.gcs_writer import download_file_from_gcs
from src.shared.translations import get_text


def _format_value(value) -> str:
    if value is None or value == "":
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _resolve_supplier_name(event: dict) -> str:
    supplier_code = str(event.get("supplier_code") or "UNKNOWN")
    supplier_name = event.get("supplier_name")
    if supplier_name:
        return str(supplier_name)
    if supplier_code and supplier_code.upper() != "UNKNOWN":
        try:
            supplier = SupplierService().get_supplier(supplier_code)
            if supplier and supplier.get("name"):
                return str(supplier["name"])
        except Exception:
            pass
    return supplier_code or "UNKNOWN"


def render_failed_event_detail(event_id: str | None = None) -> None:
    if not event_id:
        event_id = st.session_state.get("active_failed_event_id")

    if not event_id:
        st.info(get_text("failed_event_missing"))
        if st.button(get_text("order_session_back"), type="secondary"):
            st.session_state["page"] = "inbox"
            st.rerun()
        return

    event = ProcessingEventsService().get_event(str(event_id))
    if not event:
        st.error(get_text("failed_event_not_found"))
        if st.button(get_text("order_session_back"), type="secondary"):
            st.query_params.clear()
            st.session_state["page"] = "inbox"
            st.rerun()
        return

    if st.button(get_text("order_session_back"), type="secondary"):
        st.session_state.pop("active_failed_event_id", None)
        st.query_params.clear()
        st.session_state["page"] = "inbox"
        st.rerun()

    supplier_code = str(event.get("supplier_code") or "UNKNOWN")
    supplier_name = _resolve_supplier_name(event)

    st.subheader(get_text("failed_event_title"))
    st.error(get_text("failed_event_error", error=event.get("error") or "-"))

    with st.container(border=True):
        status_col, stage_col, supplier_col = st.columns(3)
        status_col.metric(get_text("inbox_col_status"), _format_value(event.get("status")))
        stage_col.metric(get_text("failed_event_stage"), _format_value(event.get("stage")))
        supplier_col.metric(get_text("metric_supplier"), f"{supplier_name} ({supplier_code})")

        st.divider()
        left, right = st.columns(2)
        with left:
            st.markdown(f"**{get_text('failed_event_created_at')}:** {_format_value(event.get('created_at'))}")
            st.markdown(f"**{get_text('failed_event_updated_at')}:** {_format_value(event.get('updated_at'))}")
            st.markdown(f"**{get_text('failed_event_filename')}:** {_format_value(event.get('filename'))}")
            st.markdown(f"**{get_text('failed_event_gcs_uri')}:** {_format_value(event.get('gcs_uri'))}")
        with right:
            st.markdown(f"**{get_text('failed_event_sender')}:** {_format_value(event.get('sender'))}")
            st.markdown(f"**{get_text('failed_event_subject')}:** {_format_value(event.get('subject'))}")
            st.markdown(f"**{get_text('failed_event_message_id')}:** {_format_value(event.get('message_id'))}")
            st.markdown(f"**{get_text('failed_event_thread_id')}:** {_format_value(event.get('thread_id'))}")
            st.markdown(
                f"**{get_text('failed_event_email_status')}:** "
                f"{_format_value(event.get('feedback_email_status'))} "
                f"({_format_value(event.get('feedback_email_attempts'))})"
            )

    source_uri = event.get("gcs_uri")
    filename = str(event.get("filename") or "source_document")
    ext = os.path.splitext(filename)[1] or os.path.splitext(str(source_uri or "").split("/")[-1])[1] or ".bin"
    download_name = filename if filename and filename != "-" else f"failed_event_{event_id}{ext}"

    st.divider()
    if source_uri:
        if st.button(get_text("order_session_download_source"), type="secondary", width="stretch"):
            tmp = f"failed_event_{os.getpid()}{ext}"
            try:
                if download_file_from_gcs(source_uri, tmp):
                    with open(tmp, "rb") as fh:
                        st.session_state["_failed_src_file_bytes"] = fh.read()
                    st.session_state["_failed_src_file_name"] = download_name
                    st.rerun()
                else:
                    st.error(get_text("retry_fail_download"))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
    else:
        st.button(
            get_text("order_session_download_source"),
            disabled=True,
            type="secondary",
            width="stretch",
            help=get_text("failed_event_no_source"),
        )

    if "_failed_src_file_bytes" in st.session_state:
        st.download_button(
            label=get_text("order_session_download_source"),
            data=st.session_state["_failed_src_file_bytes"],
            file_name=st.session_state.get("_failed_src_file_name", download_name),
            type="secondary",
        )
        del st.session_state["_failed_src_file_bytes"]
