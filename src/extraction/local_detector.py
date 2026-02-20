
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
                       email_metadata: dict[str, str] = None,
                       debug: bool = False) -> tuple | dict:
        """
        Main entry point.
        Normally returns: (supplier_code, confidence, method_used)
        If debug=True returns: {"code": str, "conf": float, "method": str, "raw_text": str, "found_identifiers": list}
        """
        # 1. Check Email Metadata (Fastest)
        if email_metadata:
            code, conf, found_ids = self._check_metadata(email_metadata, return_all=debug)
            if code and not debug:
                return code, conf, "metadata"
            elif debug:
                return {
                    "code": code or "UNKNOWN", 
                    "conf": conf, 
                    "method": "metadata" if code else "none", 
                    "raw_text": f"Subject: {email_metadata.get('subject', '')}\nBody: {email_metadata.get('body', '')}", 
                    "found_identifiers": found_ids
                }

        # 2. Check File Content
        if not os.path.exists(file_path):
            return {"code": "UNKNOWN", "conf": 0.0, "method": "none", "raw_text": "", "found_identifiers": []} if debug else ("UNKNOWN", 0.0, "none")

        text = ""
        if mime_type == "application/pdf":
            text = self._extract_text_pdf(file_path)
        elif mime_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel", "text/csv"]:
            text = self._extract_text_excel(file_path, mime_type)
        
        if not text:
            return {"code": "UNKNOWN", "conf": 0.0, "method": "none", "raw_text": "", "found_identifiers": []} if debug else ("UNKNOWN", 0.0, "none")

        # 3. Match Identifiers in Text
        code, conf, all_identifiers = self._match_identifiers(text, return_all=debug)
        
        if debug:
            return {
                "code": code or "UNKNOWN",
                "conf": conf,
                "method": "content_regex" if code else "none",
                "raw_text": text,
                "found_identifiers": all_identifiers
            }

        if code:
            return code, conf, "content_regex"

        return "UNKNOWN", 0.0, "none"

    def _check_metadata(self, metadata: dict[str, str], return_all=False) -> tuple[str | None, float, list]:
        """Checks Sender, Subject, Body for matches."""
        sender = metadata.get("sender", "").lower()
        subject = metadata.get("subject", "")
        body = metadata.get("body", "")
        
        found_ids = []
        
        # 1. Sender Email Match
        # Extract email from "Name <email@domain.com>" format if needed
        email_match = re.search(REGEX_EMAIL, sender)
        if email_match:
            email = email_match.group(0).lower()
            found_ids.append(email)
            if not self._is_blacklisted_email(email):
                code = self.supplier_service.match_supplier(email=email)
                if code != "UNKNOWN":
                    logger.info(f"✅ Local Match by Sender Email: {email} -> {code}")
                    if not return_all:
                        return code, 1.0, found_ids

        # 2. Subject/Body ID Match
        # Combine subject and body for text search
        text_to_scan = f"{subject} {body}"
        code, conf, more_ids = self._match_identifiers(text_to_scan, return_all=return_all)
        found_ids.extend(more_ids)
        
        if code and not return_all:
            logger.info(f"✅ Local Match by Metadata Text -> {code}")
            return code, conf, found_ids

        return code, conf, found_ids

    def _match_identifiers(self, text: str, return_all=False) -> tuple[str | None, float, list]:
        """Finds IDs/Emails in text and checks DB."""
        found_identifiers = []
        best_code = None
        best_conf = 0.0
        
        # Check IDs first (Strongest)
        # Using strict regex from prototype
        for match in re.finditer(REGEX_ISRAELI_ID, text):
            val = match.group(1)
            found_identifiers.append(val)
            if val not in self.blacklist_ids:
                code = self.supplier_service.match_supplier(global_id=val)
                if code != "UNKNOWN" and not best_code:
                    best_code, best_conf = code, 1.0
                    if not return_all:
                        return best_code, best_conf, found_identifiers

        # Check Emails
        # Case insensitive
        emails = re.findall(REGEX_EMAIL, text)
        for email in emails:
            email_lower = email.lower()
            found_identifiers.append(email_lower)
            if not self._is_blacklisted_email(email_lower):
                code = self.supplier_service.match_supplier(email=email_lower)
                if code != "UNKNOWN" and not best_code:
                    # Email match is very strong if unique
                    best_code, best_conf = code, 1.0
                    if not return_all:
                        return best_code, best_conf, found_identifiers

        return best_code, best_conf, list(set(found_identifiers))

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
