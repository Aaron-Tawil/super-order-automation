"""
Supplier Service for matching suppliers from orders to internal codes.

Matching priority:
1. Global ID (עוסק/ח"פ) - direct lookup
2. Phone number - exact match
3. Email (exact) - exact email match
4. Email (domain) - match by email domain (excluding common domains)
5. Name (exact) - exact name match
6. Name (fuzzy) - fuzzy matching with high threshold
7. Fallback - return "UNKNOWN"
"""

import io
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Constant for unknown supplier
UNKNOWN_SUPPLIER = "UNKNOWN"

# Excluded email domains - don't match suppliers by these domains
EXCLUDED_EMAIL_DOMAINS = {
    # Free email providers
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "aol.com",
    "icloud.com",
    "mail.com",
    "protonmail.com",
    "zoho.com",
    "yandex.com",
    # Israeli ISP emails
    "walla.co.il",
    "walla.com",
    "012.net.il",
    "netvision.net.il",
    "bezeqint.net",
    "zahav.net.il",
    "013.net",
    "smile.net.il",
    "013net.net",
    "barak.net.il",
    "internet-zahav.net",
    # Your company domains (don't match to self)
    "superhome.co.il",
}

# CSV Cache TTL (Time-To-Live) - fallback when no _meta document exists
CSV_CACHE_TTL = timedelta(hours=24)


class SupplierService:
    """Service for supplier matching and lookup."""

    # Metadata document ID for tracking last modification
    META_DOC_ID = "_meta"

    def __init__(self, firestore_client: firestore.Client = None):
        """
        Initialize the supplier service.

        Args:
            firestore_client: Optional Firestore client. If not provided, creates one.
        """
        if firestore_client:
            self._db = firestore_client
        else:
            from src.shared.config import settings

            self._db = firestore.Client(project=settings.PROJECT_ID)
        self._collection = self._db.collection("suppliers")
        self._meta_doc = self._collection.document(self.META_DOC_ID)

        # Cache for global_id -> supplier_code mapping
        self._global_id_cache: dict[str, str] = {}
        # Cache for email -> supplier_code mapping
        self._email_cache: dict[str, str] = {}
        # Cache for phone -> supplier_code mapping
        self._phone_cache: dict[str, str] = {}
        # Cache for domain -> supplier_code mapping
        self._domain_cache: dict[str, str] = {}
        # Cache for name -> supplier_code mapping
        self._name_cache: dict[str, str] = {}
        # All suppliers data for CSV generation and fuzzy matching
        self._all_suppliers: list[dict] = []

        self._cache_loaded = False

        # CSV cache for LLM context
        self._csv_cache: str | None = None
        self._csv_cache_timestamp: datetime | None = None
        # Track the meta timestamp we cached against
        self._cached_meta_timestamp: datetime | None = None

    def _ensure_cache_loaded(self):
        """Load supplier lookups into memory cache."""
        if self._cache_loaded:
            return

        logger.info("Loading suppliers cache from Firestore...")
        docs = self._collection.stream()

        for doc in docs:
            supplier_code = doc.id
            data = doc.to_dict()

            # Store full supplier data for CSV generation and fuzzy matching
            supplier_record = {
                "code": supplier_code,
                "name": data.get("name", ""),
                "global_id": data.get("global_id", ""),
                "email": data.get("email", ""),
                "phone": data.get("phone", ""),
                "special_instructions": data.get("special_instructions", ""),
            }
            self._all_suppliers.append(supplier_record)

            # Index by global_id
            global_id = data.get("global_id")
            if global_id:
                self._global_id_cache[str(global_id).strip()] = supplier_code

            # Index by email (lowercase)
            email = data.get("email")
            additional_emails = data.get("additional_emails", [])
            
            # Combine primary email and additional emails
            all_emails = []
            if email:
                all_emails.append(str(email).strip().lower())
            
            if additional_emails:
                for ae in additional_emails:
                    if ae:
                        all_emails.append(str(ae).strip().lower())
            
            for e in all_emails:
                self._email_cache[e] = supplier_code

                # Index by domain (but exclude common domains)
                if "@" in e:
                    domain = e.split("@")[-1]
                    if domain not in EXCLUDED_EMAIL_DOMAINS:
                        self._domain_cache[domain] = supplier_code

            # Index by phone
            phone = data.get("phone")
            if phone:
                # Basic cleaning: remove dashes, spaces
                clean_phone = "".join(filter(str.isdigit, str(phone)))
                if clean_phone:
                    self._phone_cache[clean_phone] = supplier_code

            # Index by name
            name = data.get("name")
            if name:
                clean_name = str(name).strip().lower()
                self._name_cache[clean_name] = supplier_code

        logger.info(
            f"Suppliers cache loaded: {len(self._all_suppliers)} suppliers, "
            f"{len(self._global_id_cache)} global_ids, {len(self._phone_cache)} phones, "
            f"{len(self._email_cache)} emails, {len(self._domain_cache)} domains, "
            f"{len(self._name_cache)} names"
        )
        self._cache_loaded = True

    def match_supplier(self, global_id: str = None, email: str = None, phone: str = None, name: str = None) -> str:
        """
        Match a supplier to an internal supplier code.

        Tries matching in order:
        1. Global ID (עוסק/ח"פ)
        2. Email address
        3. Returns "UNKNOWN" if no match

        Args:
            global_id: The supplier's global ID (עוסק/ח"פ)
            email: The supplier's email address
            name: The supplier's name (currently unused, for future fuzzy matching)

        Returns:
            Internal supplier code or "UNKNOWN"
        """
        self._ensure_cache_loaded()

        # Try global_id first
        if global_id:
            global_id = str(global_id).strip()
            if global_id in self._global_id_cache:
                code = self._global_id_cache[global_id]
                logger.info(f"Matched supplier by global_id {global_id} -> {code}")
                return code

        # Try phone
        if phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))
            if clean_phone and clean_phone in self._phone_cache:
                code = self._phone_cache[clean_phone]
                logger.info(f"Matched supplier by phone {phone} -> {code}")
                return code

        # Try email domain matching (Priority over exact email for this request)
        if email:
            email = str(email).strip().lower()

            # 1. Try exact email match (legacy/fast)
            if email in self._email_cache:
                code = self._email_cache[email]
                logger.info(f"Matched supplier by exact email {email} -> {code}")
                return code

            # 2. Try domain match
            if "@" in email:
                domain = email.split("@")[-1]
                if domain in self._domain_cache:
                    code = self._domain_cache[domain]
                    logger.info(f"Matched supplier by email domain {domain} -> {code}")
                    return code

        # Try name (Exact match, normalized)
        if name:
            clean_name = str(name).strip().lower()
            if clean_name in self._name_cache:
                code = self._name_cache[clean_name]
                logger.info(f"Matched supplier by name '{name}' -> {code}")
                return code

        # No match found
        logger.warning(
            f"Could not match supplier - global_id: {global_id}, phone: {phone}, email: {email}, name: {name}"
        )
        return UNKNOWN_SUPPLIER

    def get_supplier(self, supplier_code: str) -> dict | None:
        """
        Get supplier details by code.

        Args:
            supplier_code: The internal supplier code

        Returns:
            Supplier data dict or None if not found
        """
        doc = self._collection.document(str(supplier_code)).get()

        if doc.exists:
            return doc.to_dict()
        return None

    def is_unknown(self, supplier_code: str) -> bool:
        """Check if the supplier code represents an unknown supplier."""
        return supplier_code == UNKNOWN_SUPPLIER

    def get_supplier_instructions(self, supplier_code: str) -> str | None:
        """
        Get special extraction instructions for a supplier.

        Args:
            supplier_code: The internal supplier code

        Returns:
            Special instructions string or None if not set
        """
        if supplier_code == UNKNOWN_SUPPLIER:
            return None

        doc = self._collection.document(str(supplier_code)).get()

        if doc.exists:
            data = doc.to_dict()
            return data.get("special_instructions")
        return None

    def update_supplier_instructions(self, supplier_code: str, instructions: str) -> bool:
        """
        Update/save special extraction instructions for a supplier.

        Args:
            supplier_code: The internal supplier code
            instructions: The special instructions text

        Returns:
            True if update successful, False otherwise
        """
        if supplier_code == UNKNOWN_SUPPLIER:
            logger.warning("Cannot update instructions for UNKNOWN supplier")
            return False

        try:
            doc_ref = self._collection.document(str(supplier_code))
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"Supplier {supplier_code} not found")
                return False

            doc_ref.update({"special_instructions": instructions})
            logger.info(f"Updated instructions for supplier {supplier_code}")

            # Invalidate cache and update metadata timestamp
            self.invalidate_cache()
            self._update_meta_timestamp()

            return True
        except Exception as e:
            logger.error(f"Error updating supplier instructions: {e}")
            return False

    def add_supplier(
        self,
        supplier_code: str,
        name: str,
        global_id: str = None,
        email: str = None,
        phone: str = None,
        special_instructions: str = None,
    ) -> bool:
        """
        Add a new supplier to the database.

        Args:
            supplier_code: Unique supplier code (will be the document ID)
            name: Supplier display name (required)
            global_id: Business registration number (עוסק/ח"פ)
            email: Supplier email address
            phone: Supplier phone number
            special_instructions: Special extraction instructions

        Returns:
            True if added successfully, False otherwise
        """
        if not supplier_code or not name:
            logger.warning("Supplier code and name are required")
            return False

        if supplier_code == UNKNOWN_SUPPLIER or supplier_code == self.META_DOC_ID:
            logger.warning(f"Cannot use reserved supplier code: {supplier_code}")
            return False

        try:
            doc_ref = self._collection.document(str(supplier_code))

            # Check if already exists
            if doc_ref.get().exists:
                logger.warning(f"Supplier {supplier_code} already exists")
                return False

            # Create the supplier document
            supplier_data = {
                "name": name,
                "global_id": global_id or "",
                "email": email or "",
                "phone": phone or "",
                "special_instructions": special_instructions or "",
                "created_at": datetime.now(),
            }

            doc_ref.set(supplier_data)
            logger.info(f"Added new supplier: {supplier_code}")

            # Invalidate cache and update metadata timestamp
            self.invalidate_cache()
            self._update_meta_timestamp()

            return True
        except Exception as e:
            logger.error(f"Error adding supplier: {e}")
            return False

    def update_supplier(
        self,
        supplier_code: str,
        name: str = None,
        global_id: str = None,
        email: str = None,
        phone: str = None,
        special_instructions: str = None,
    ) -> bool:
        """
        Update an existing supplier's details.

        Args:
            supplier_code: The supplier code to update
            name: New name (if provided)
            global_id: New global ID (if provided)
            email: New email (if provided)
            phone: New phone (if provided)
            special_instructions: New instructions (if provided)

        Returns:
            True if updated successfully, False otherwise
        """
        if supplier_code == UNKNOWN_SUPPLIER or supplier_code == self.META_DOC_ID:
            logger.warning(f"Cannot update reserved supplier code: {supplier_code}")
            return False

        try:
            doc_ref = self._collection.document(str(supplier_code))
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"Supplier {supplier_code} not found")
                return False

            # Build update dict with only provided fields
            update_data = {}
            if name is not None:
                update_data["name"] = name
            if global_id is not None:
                update_data["global_id"] = global_id
            if email is not None:
                update_data["email"] = email
            if phone is not None:
                update_data["phone"] = phone
            if special_instructions is not None:
                update_data["special_instructions"] = special_instructions

            if not update_data:
                logger.warning("No fields to update")
                return False

            update_data["updated_at"] = datetime.now()

            doc_ref.update(update_data)
            logger.info(f"Updated supplier: {supplier_code}")

            # Invalidate cache and update metadata timestamp
            self.invalidate_cache()
            self._update_meta_timestamp()

            return True
        except Exception as e:
            logger.error(f"Error updating supplier: {e}")
            return False

    def add_email_to_supplier(self, supplier_code: str, email: str) -> bool:
        """
        Add a new email to an existing supplier's additional_emails list.
        Performs a GLOBAL check to ensure email isn't already assigned to another supplier.
        
        Args:
            supplier_code: The supplier code to update
            email: The new email to add
            
        Returns:
            True if updated successfully or already exists, False if conflict or error
        """
        if supplier_code == UNKNOWN_SUPPLIER:
            return False
            
        # Normalize
        new_email = email.strip().lower()
        
        # 1. Global Conflict Check
        # Ensure regex/db cache is loaded to check if this email is already known
        self._ensure_cache_loaded()
        
        if new_email in self._email_cache:
            existing_code = self._email_cache[new_email]
            if existing_code != supplier_code:
                logger.warning(f"⚠️ Email {new_email} already assigned to DIFFERENT supplier {existing_code}. Cannot add to {supplier_code}.")
                return False
            else:
                logger.info(f"Email {new_email} already linked to this supplier ({supplier_code}).")
                return True

        try:
            doc_ref = self._collection.document(str(supplier_code))
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"Supplier {supplier_code} not found")
                return False

            data = doc.to_dict()
            current_emails = data.get("additional_emails", [])
            
            # Double check current_emails (though global cache should have caught it)
            if new_email in [e.lower() for e in current_emails]:
                return True 
                
            # Check if match primary email
            primary_email = str(data.get("email", "")).lower()
            if new_email == primary_email:
                return True
                
            # Add and update
            current_emails.append(new_email)
            doc_ref.update({"additional_emails": current_emails, "updated_at": datetime.now()})
            
            logger.info(f"Added email {new_email} to supplier {supplier_code}")
            
            # Invalidate cache
            self.invalidate_cache()
            self._update_meta_timestamp()
            
            return True
        except Exception as e:
            logger.error(f"Error adding email to supplier: {e}")
            return False

    def update_missing_global_id(self, supplier_code: str, new_global_id: str) -> bool:
        """
        Update a supplier's global_id only if it is currently missing.
        Performs a GLOBAL check to ensure ID isn't already assigned to another supplier.

        Args:
            supplier_code: The supplier code to update
            new_global_id: The detected global ID

        Returns:
            True if updated successfully or already matched, False otherwise
        """
        if supplier_code == UNKNOWN_SUPPLIER or not new_global_id:
            return False

        # Clean ID (remove internal chars)
        cleaned_id = str(new_global_id).strip()
        if not cleaned_id:
            return False
            
        # 1. Global Conflict Check
        self._ensure_cache_loaded()
        if cleaned_id in self._global_id_cache:
            existing_code = self._global_id_cache[cleaned_id]
            if existing_code != supplier_code:
                logger.warning(f"⚠️ ID {cleaned_id} already assigned to DIFFERENT supplier {existing_code}. Cannot assign to {supplier_code}.")
                return False
            else:
                logger.info(f"ID {cleaned_id} already matches this supplier ({supplier_code}).")
                return True

        try:
            doc_ref = self._collection.document(str(supplier_code))
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"Supplier {supplier_code} not found")
                return False

            data = doc.to_dict()
            current_id = str(data.get("global_id", "")).strip()

            if current_id:
                # ID already exists - do NOT overwrite (safety)
                if current_id != cleaned_id:
                    logger.warning(f"Supplier {supplier_code} already has ID {current_id}, ignoring detected {cleaned_id}")
                return False # Already has an ID, don't change it automatically

            # Update
            doc_ref.update({"global_id": cleaned_id, "updated_at": datetime.now()})
            logger.info(f"🎉 Auto-Learned: Added Global ID {cleaned_id} to supplier {supplier_code}")

            # Invalidate cache
            self.invalidate_cache()
            self._update_meta_timestamp()
            
            return True
        except Exception as e:
            logger.error(f"Error updating global ID for supplier: {e}")
            return False

    def get_all_suppliers(self) -> list:
        """
        Get all suppliers from the database (uses cached data).

        Returns:
            List of supplier dicts with code and details
        """
        self._ensure_cache_loaded()
        return self._all_suppliers.copy()

    def _get_meta_timestamp(self) -> datetime | None:
        """Get the last_modified timestamp from the metadata document."""
        try:
            doc = self._meta_doc.get()
            if doc.exists:
                data = doc.to_dict()
                ts = data.get("last_modified")
                if ts:
                    # Firestore returns datetime objects directly
                    return ts if isinstance(ts, datetime) else None
            return None
        except Exception as e:
            logger.warning(f"Could not read meta timestamp: {e}")
            return None

    def _update_meta_timestamp(self):
        """Update the last_modified timestamp in the metadata document."""
        try:
            self._meta_doc.set({"last_modified": datetime.now(), "updated_by": "supplier_service"}, merge=True)
            logger.info("Updated suppliers metadata timestamp")
        except Exception as e:
            logger.error(f"Failed to update meta timestamp: {e}")

    def get_suppliers_csv(self) -> str:
        """
        Get suppliers data as CSV text for LLM context.
        Uses metadata-based caching - only regenerates if suppliers have changed.

        Returns:
            CSV formatted string of supplier data
        """
        # Get the current metadata timestamp
        meta_timestamp = self._get_meta_timestamp()

        # Check if cache is valid:
        # 1. Cache exists
        # 2. Meta timestamp exists and matches what we cached against
        # 3. OR meta doesn't exist but cache is within TTL (fallback)
        if self._csv_cache:
            if meta_timestamp and self._cached_meta_timestamp:
                # Compare with cached meta timestamp
                if meta_timestamp <= self._cached_meta_timestamp:
                    logger.debug("CSV cache valid (meta timestamp unchanged)")
                    return self._csv_cache
            elif not meta_timestamp and self._csv_cache_timestamp:
                # No meta doc exists, fall back to TTL
                age = datetime.now() - self._csv_cache_timestamp
                if age < CSV_CACHE_TTL:
                    return self._csv_cache

        # Regenerate from Firestore
        logger.info("Regenerating suppliers CSV from Firestore...")
        self._ensure_cache_loaded()

        # Build CSV
        output = io.StringIO()
        output.write("קוד,שם,עוסק_מורשה,טלפון,אימייל\n")

        for supplier in self._all_suppliers:
            code = supplier.get("code", "")
            name = supplier.get("name", "")
            global_id = supplier.get("global_id", "")
            phone = supplier.get("phone", "")
            email = supplier.get("email", "")

            # Escape commas in fields
            name = name.replace(",", " ")

            output.write(f"{code},{name},{global_id},{phone},{email}\n")

        self._csv_cache = output.getvalue()
        self._csv_cache_timestamp = datetime.now()
        self._cached_meta_timestamp = meta_timestamp or datetime.now()

        logger.info(f"Generated suppliers CSV with {len(self._all_suppliers)} entries")
        return self._csv_cache

    def invalidate_cache(self):
        """Force cache invalidation. Call when suppliers are modified externally."""
        self._cache_loaded = False
        self._all_suppliers = []
        self._global_id_cache = {}
        self._email_cache = {}
        self._phone_cache = {}
        self._domain_cache = {}
        self._name_cache = {}
        self._csv_cache = None
        self._csv_cache_timestamp = None
        self._cached_meta_timestamp = None
        logger.info("Supplier cache invalidated")

    def fuzzy_match_name(self, query: str) -> tuple[str, float] | None:
        """
        Attempt fuzzy matching on supplier name.

        Uses conservative settings to minimize false positives:
        - Requires >85% similarity
        - Returns None if multiple candidates match (ambiguous)

        Args:
            query: The supplier name to search for

        Returns:
            Tuple of (supplier_code, similarity_score) or None if no confident match
        """
        if not query:
            return None

        self._ensure_cache_loaded()

        # Try to import rapidfuzz, return None if not available
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed, fuzzy matching disabled")
            return None

        # Normalize query
        query_normalized = query.strip().lower()

        SIMILARITY_THRESHOLD = 85  # High threshold to reduce false positives
        matches = []

        for supplier in self._all_suppliers:
            name = supplier.get("name", "")
            if not name:
                continue

            name_normalized = name.strip().lower()
            score = fuzz.ratio(query_normalized, name_normalized)

            if score >= SIMILARITY_THRESHOLD:
                matches.append((supplier["code"], score, name))

        # Only return if exactly ONE strong match (no ambiguity)
        if len(matches) == 1:
            code, score, matched_name = matches[0]
            logger.info(f"Fuzzy matched '{query}' -> '{matched_name}' (code: {code}, score: {score})")
            return (code, score / 100.0)  # Return as 0-1 scale
        elif len(matches) > 1:
            logger.warning(f"Fuzzy match ambiguous for '{query}': {len(matches)} candidates found")
            return None

        return None
