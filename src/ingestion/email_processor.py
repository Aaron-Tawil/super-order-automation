import base64
import json
import mimetypes
import os
import pickle
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.core.exceptions import ExtractionError, SupplierMatchError, ValidationError
from src.core.processor import OrderProcessor
from src.data.items_service import ItemsService
from src.data.supplier_service import UNKNOWN_SUPPLIER, SupplierService
from src.export.excel_generator import generate_excel_from_order
from src.export.new_items_generator import filter_new_items_from_order, generate_new_items_excel
from src.extraction.vertex_client import detect_supplier, init_client
from src.ingestion.gcs_writer import upload_to_gcs
from src.ingestion.ingestor import IngestionService
from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.session_store import create_session
from src.shared.translations import get_text

logger = get_logger(__name__)


def process_unread_emails() -> int:
    """
    Scans for unread emails and processes them asynchronously via IngestionService.
    Returns: Number of emails ingested.
    """
    try:
        service = IngestionService()
        count = service.process_unread_emails_async()
        if count > 0:
            logger.info(f"Async Ingestion: Successfully published events for {count} emails.")
        return count
    except Exception as e:
        logger.error(f"Failed to process unread emails: {e}", exc_info=True)
        return 0
