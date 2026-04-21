"""
Build and send queued response emails from durable outbox records.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from src.data.orders_service import OrdersService
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import generate_new_items_excel
from src.ingestion.gcs_writer import download_file_from_gcs
from src.ingestion.gmail_utils import (
    SEND_REPLY_STATUS_PERMANENT_FAILED,
    SEND_REPLY_STATUS_RETRYABLE_FAILED,
    SEND_REPLY_STATUS_SENT,
    normalize_email_subject,
    send_reply_with_status,
)
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder, LineItem

logger = get_logger(__name__)

OUTBOX_SEND_SENT = SEND_REPLY_STATUS_SENT
OUTBOX_SEND_RETRYABLE_FAILED = SEND_REPLY_STATUS_RETRYABLE_FAILED
OUTBOX_SEND_PERMANENT_FAILED = SEND_REPLY_STATUS_PERMANENT_FAILED


def _safe_suffix(filename: str | None, default: str = ".bin") -> str:
    suffix = os.path.splitext(str(filename or ""))[1]
    return suffix if suffix else default


def _named_temp_path(prefix: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(fd)
    return path


def _prepare_attachment(ref: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    ref_type = str(ref.get("type") or "").strip()
    filename = str(ref.get("filename") or "attachment")

    if ref_type == "gcs_source":
        gcs_uri = ref.get("gcs_uri")
        if not gcs_uri:
            return None, None, "Missing gcs_uri for source attachment"
        path = _named_temp_path("email_source_", _safe_suffix(filename))
        if not download_file_from_gcs(str(gcs_uri), path):
            if os.path.exists(path):
                os.remove(path)
            return None, None, f"Failed to download source attachment {gcs_uri}"
        return path, filename, None

    if ref_type == "order_excel":
        order_id = ref.get("order_id")
        if not order_id:
            return None, None, "Missing order_id for order Excel attachment"
        order_doc = OrdersService().get_order(str(order_id))
        if not order_doc:
            return None, None, f"Order {order_id} not found for email attachment"
        order = ExtractedOrder.model_validate(order_doc)
        path = _named_temp_path("email_order_", ".xlsx")
        generate_excel_from_order(order, path)
        return path, filename, None

    if ref_type == "new_items_excel":
        order_id = ref.get("order_id")
        if not order_id:
            return None, None, "Missing order_id for new-items attachment"
        order_doc = OrdersService().get_order(str(order_id))
        if not order_doc:
            return None, None, f"Order {order_id} not found for new-items attachment"
        new_items = order_doc.get("new_items") or []
        line_items = [LineItem(**item) for item in new_items]
        path = _named_temp_path("email_new_items_", ".xlsx")
        generate_new_items_excel(line_items, str(ref.get("supplier_code") or "UNKNOWN"), path)
        return path, filename, None

    return None, None, f"Unknown attachment ref type: {ref_type or '-'}"


def send_outbox_email(email: dict, gmail_service) -> tuple[str, str | None]:
    """Send one queued email, rebuilding attachments from durable references."""
    required = ("thread_id", "message_id", "to", "body")
    missing = [field for field in required if not email.get(field)]
    if missing:
        return OUTBOX_SEND_PERMANENT_FAILED, f"Missing email fields: {', '.join(missing)}"
    if not gmail_service:
        return OUTBOX_SEND_RETRYABLE_FAILED, "Gmail service unavailable"

    attachment_paths: list[str] = []
    attachment_names: dict[str, str] = {}
    try:
        for ref in email.get("attachment_refs") or []:
            path, filename, error = _prepare_attachment(ref)
            if error:
                if error.startswith("Failed to download source attachment"):
                    return OUTBOX_SEND_RETRYABLE_FAILED, error
                return OUTBOX_SEND_PERMANENT_FAILED, error
            if path:
                attachment_paths.append(path)
                if filename:
                    attachment_names[path] = filename

        return send_reply_with_status(
            gmail_service,
            email["thread_id"],
            email["message_id"],
            email["to"],
            normalize_email_subject(email.get("subject")),
            email["body"],
            attachment_paths=attachment_paths,
            attachment_names=attachment_names,
            is_html=bool(email.get("is_html")),
        )
    except Exception as e:
        logger.error(f"Failed sending outbox email {email.get('outbox_id')}: {e}", exc_info=True)
        return OUTBOX_SEND_RETRYABLE_FAILED, str(e)
    finally:
        for path in attachment_paths:
            if path and os.path.exists(path):
                os.remove(path)
