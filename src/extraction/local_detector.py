
import os
import re
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
from pypdf import PdfReader

from src.data.supplier_service import SupplierService
from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

# --- Regex Patterns ---
# 9-digit Israeli Business ID (Osek Murshe / H.P.)
# Matches 9 consecutive digits. Must NOT be preceded or followed by a digit.
REGEX_ISRAELI_ID = r"(?<!\d)(\d{9})(?!\d)"

# Email Addresses
REGEX_EMAIL = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"


class LocalSupplierDetector:
    """
    Attempts to detect the supplier locally using Metadata, PDF text, or Excel content.
    Bypasses Vertex AI if a strong match is found.
    """

    def __init__(self):
        self.supplier_service = SupplierService()
        self.supplier_service._ensure_cache_loaded()
        
        # Load Blacklists from Config
        self.blacklist_ids = settings.blacklist_ids
        self.blacklist_emails = settings.blacklist_emails
        
        logger.info(f"LocalDetector initialized. Blacklist: {len(self.blacklist_ids)} IDs, {len(self.blacklist_emails)} Emails.")

    def detect_supplier(self, 
                       file_path: str, 
                       mime_type: str, 
                       email_metadata: dict[str, str] = None) -> tuple[str, float, str]:
        """
        Main entry point.
        Returns: (supplier_code, confidence, method_used)
        
        Confidence:
            1.0 = Exact Match (Metadata or ID)
            0.8 = Strong Match (Email in file)
            0.0 = No Match
        """
        # 1. Check Email Metadata (Fastest)
        if email_metadata:
            code, conf = self._check_metadata(email_metadata)
            if code:
                return code, conf, "metadata"

        # 2. Check File Content
        if not os.path.exists(file_path):
            return "UNKNOWN", 0.0, "none"

        text = ""
        if mime_type == "application/pdf":
            text = self._extract_text_pdf(file_path)
        elif mime_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel", "text/csv"]:
            text = self._extract_text_excel(file_path, mime_type)
        
        if not text:
            return "UNKNOWN", 0.0, "none"

        # 3. Match Identifiers in Text
        code, conf = self._match_identifiers(text)
        if code:
            return code, conf, "content_regex"

        return "UNKNOWN", 0.0, "none"

    def _check_metadata(self, metadata: dict[str, str]) -> tuple[str | None, float]:
        """Checks Sender, Subject, Body for matches."""
        sender = metadata.get("sender", "").lower()
        subject = metadata.get("subject", "")
        body = metadata.get("body", "")
        
        # 1. Sender Email Match
        # Extract email from "Name <email@domain.com>" format if needed
        email_match = re.search(REGEX_EMAIL, sender)
        if email_match:
            email = email_match.group(0).lower()
            if not self._is_blacklisted_email(email):
                code = self.supplier_service.match_supplier(email=email)
                if code != "UNKNOWN":
                    logger.info(f"✅ Local Match by Sender Email: {email} -> {code}")
                    return code, 1.0

        # 2. Subject/Body ID Match
        # Combine subject and body for text search
        text_to_scan = f"{subject} {body}"
        code, conf = self._match_identifiers(text_to_scan)
        if code:
            logger.info(f"✅ Local Match by Metadata Text -> {code}")
            return code, conf

        return None, 0.0

    def _match_identifiers(self, text: str) -> tuple[str | None, float]:
        """Finds IDs/Emails in text and checks DB."""
        
        # Check IDs first (Strongest)
        # Using strict regex from prototype
        for match in re.finditer(REGEX_ISRAELI_ID, text):
            val = match.group(1)
            if val not in self.blacklist_ids:
                code = self.supplier_service.match_supplier(global_id=val)
                if code != "UNKNOWN":
                    return code, 1.0

        # Check Emails
        # Case insensitive
        emails = re.findall(REGEX_EMAIL, text)
        for email in emails:
            email_lower = email.lower()
            if not self._is_blacklisted_email(email_lower):
                code = self.supplier_service.match_supplier(email=email_lower)
                if code != "UNKNOWN":
                    # Email match is very strong if unique
                    return code, 1.0

        return None, 0.0

    def _is_blacklisted_email(self, email: str) -> bool:
        """Checks if email is in blacklist OR matches a blacklisted domain (@domain.com)."""
        if email in self.blacklist_emails:
            return True
        
        # Check for domain wildcards
        for blocked in self.blacklist_emails:
            if blocked.startswith("@") and email.endswith(blocked):
                return True
        
        return False

    def _extract_text_pdf(self, file_path: str) -> str:
        """Extracts text from FIRST page of PDF."""
        try:
            reader = PdfReader(file_path)
            if reader.pages:
                return reader.pages[0].extract_text() or ""
        except Exception as e:
            logger.warning(f"PDF extract error for {file_path}: {e}")
        return ""

    def _extract_text_excel(self, file_path: str, mime_type: str) -> str:
        """Extracts text from Excel/CSV (limited to first few rows/cols for speed)."""
        try:
            # Read first 20 rows to catch header/supplier info
            df = None
            if "csv" in mime_type.lower():
                df = pd.read_csv(file_path, nrows=20, header=None)
            else:
                # default to excel for other mime types
                df = pd.read_excel(file_path, nrows=20, header=None)
            
            if df is not None:
                # Convert to string blob
                return df.to_string(index=False, header=False)
        except Exception as e:
            logger.warning(f"Excel extract error for {file_path}: {e}")
        return ""
