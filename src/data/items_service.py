"""
Items Service for barcode lookup and new item detection.

Uses Firestore as the backing store with in-memory caching for performance.
"""

import logging
from typing import List, Optional, Set

from google.cloud import firestore
from google.cloud.firestore import FieldFilter

logger = logging.getLogger(__name__)


class ItemsService:
    """Service for managing items/barcodes database."""

    def get_total_items_count(self) -> int:
        """
        Get the total number of items in the database.

        Returns:
            Total count of items.
        """
        # Using aggregation query for fast counting
        # Note: This incurs 1 document read cost per 1000 index entries matched,
        # which is much cheaper than reading all documents.
        aggregate_query = self._collection.count()
        results = aggregate_query.get()
        return results[0][0].value

    def __init__(self, firestore_client: firestore.Client = None):
        """
        Initialize the items service.

        Args:
            firestore_client: Optional Firestore client. If not provided, creates one.
        """
        if firestore_client:
            self._db = firestore_client
        else:
            from src.shared.config import settings

            self._db = firestore.Client(project=settings.PROJECT_ID)
        self._collection = self._db.collection("items")

    def barcode_exists(self, barcode: str) -> bool:
        """
        Check if a barcode exists in the items database.

        Args:
            barcode: The barcode to check

        Returns:
            True if barcode exists, False otherwise
        """
        barcode = str(barcode).strip()
        doc = self._collection.document(barcode).get()
        return doc.exists

    def get_new_barcodes(self, barcodes: list[str]) -> list[str]:
        """
        Filter a list of barcodes to only those not in the database.

        Args:
            barcodes: List of barcodes to check

        Returns:
            List of barcodes that don't exist in the database
        """
        barcodes = [str(b).strip() for b in barcodes if b]
        if not barcodes:
            return []

        # Deduplicate input
        unique_barcodes = list(set(barcodes))

        # Prepare all variants to check (original + stripped if applicable)
        # Map each variant back to the original barcode(s) it represents
        # So if we find "123", we know "0123" is also existing.

        # We need to know which of the *INPUT* barcodes are missing.
        # So, for each input barcode, we check if it OR its stripped version exists.

        checks = []
        for b in unique_barcodes:
            checks.append(b)
            if b.startswith("0"):
                stripped = b.lstrip("0")
                if stripped:  # Ensure we don't add empty string if barcode was just "0"
                    checks.append(stripped)

        # Deduplicate checks to save reads
        unique_checks = list(set(checks))

        # Batch get all checking documents
        # Firestore limit is 30 in a 'IN' query, but get_all supports more.
        # Ideally process in chunks if list is huge, but usually < 100 items.

        refs = [self._collection.document(b) for b in unique_checks]
        docs = self._db.get_all(refs)

        existing_ids = {doc.id for doc in docs if doc.exists}

        # Now determine which input barcodes are new
        new_barcodes = []
        for b in unique_barcodes:
            exists = False
            # Check original
            if b in existing_ids:
                exists = True
            # Check stripped
            elif b.startswith("0") and (b.lstrip("0") in existing_ids):
                exists = True

            if not exists:
                new_barcodes.append(b)

        return new_barcodes

    def add_new_item(self, barcode: str, name: str, item_code: str = None, note: str = None) -> bool:
        """
        Add a new item to the database.

        Args:
            barcode: The item barcode (used as document ID)
            name: Product name
            item_code: Optional internal item code
            note: Optional note

        Returns:
            True if item was added, False if it already exists
        """
        barcode = str(barcode).strip()
        doc_ref = self._collection.document(barcode)

        # Transactional check-and-set or just create?
        # create() fails if document exists
        try:
            doc_data = {
                "item_code": item_code,
                "name": name,
                "note": note,
            }
            doc_ref.create(doc_data)
            logger.info(f"Added new item: {barcode} - {name}")
            return True
        except Exception as e:
            # check for "already exists" error
            if "already exists" in str(e).lower() or "409" in str(e):
                logger.warning(f"Item with barcode {barcode} already exists")
                return False
            raise e

    def update_item(self, barcode: str, name: str, item_code: str = None, note: str = None) -> bool:
        """
        Update an existing item in the database.

        Args:
            barcode: The item barcode (document ID)
            name: Product name
            item_code: Optional internal item code
            note: Optional note

        Returns:
            True if item was updated, False if it doesn't exist or fails
        """
        barcode = str(barcode).strip()
        doc_ref = self._collection.document(barcode)

        try:
            doc_data = {
                "item_code": item_code,
                "name": name,
                "note": note,
            }
            # update() fails if document doesn't exist, which is what we want for strict update
            doc_ref.update(doc_data)
            logger.info(f"Updated item: {barcode} - {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to update item {barcode}: {e}")
            return False

    def add_new_items_batch(self, items: list[dict]) -> int:
        """
        Add multiple new items in a batch.

        Args:
            items: List of dicts with keys: barcode, name, item_code (optional), note (optional)

        Returns:
            Number of items successfully added
        """
        if not items:
            return 0

        # Process in chunks to avoid hitting batch limits (500 ops)
        chunk_size = 400
        total_added = 0

        # Deduplicate input items by barcode
        unique_items = {}
        for item in items:
            b = str(item.get("barcode", "")).strip()
            if b:
                unique_items[b] = item

        unique_barcodes = list(unique_items.keys())

        for i in range(0, len(unique_barcodes), chunk_size):
            chunk_barcodes = unique_barcodes[i : i + chunk_size]

            # Check existence for this chunk
            refs = [self._collection.document(b) for b in chunk_barcodes]
            docs = self._db.get_all(refs)
            existing_ids = {doc.id for doc in docs if doc.exists}

            batch = self._db.batch()
            count_in_batch = 0

            for barcode in chunk_barcodes:
                if barcode in existing_ids:
                    continue

                item = unique_items[barcode]
                doc_ref = self._collection.document(barcode)
                doc_data = {
                    "item_code": item.get("item_code"),
                    "name": item.get("name"),
                    "note": item.get("note"),
                }
                batch.set(doc_ref, doc_data)
                count_in_batch += 1

            if count_in_batch > 0:
                batch.commit()
                total_added += count_in_batch
                logger.info(f"Committed batch of {count_in_batch} items")

        if total_added > 0:
            logger.info(f"Total processed: {len(items)}. Added {total_added} new items.")

        return total_added

    def get_items_batch(self, barcodes: list[str]) -> list[dict]:
        """
        Get details for multiple items by their barcodes.
        Checks both original and stripped (no leading zeros) versions.

        Args:
            barcodes: List of barcodes to lookup

        Returns:
            List of item dicts found
        """
        if not barcodes:
            return []

        barcodes = [str(b).strip() for b in barcodes if b]
        unique_barcodes = set(barcodes)

        # Add stripped versions to lookup list to handle leading zero mismatch
        lookup_ids = set(unique_barcodes)
        for b in unique_barcodes:
            if b.startswith("0"):
                stripped = b.lstrip("0")
                if stripped:
                    lookup_ids.add(stripped)

        results = []

        refs = [self._collection.document(b) for b in list(lookup_ids)]
        import time

        t_start = time.time()
        docs = self._db.get_all(refs)
        logger.info(f"get_items_batch: Firestore get_all({len(refs)} refs) took {time.time() - t_start:.2f}s")

        for doc in docs:
            if doc.exists:
                data = doc.to_dict()
                data["barcode"] = doc.id
                results.append(data)

        return results

    def get_item(self, barcode: str) -> dict | None:
        """
        Get item details by barcode.

        Args:
            barcode: The barcode to lookup

        Returns:
            Item data dict or None if not found
        """
        barcode = str(barcode).strip()
        doc = self._collection.document(barcode).get()

        if doc.exists:
            data = doc.to_dict()
            data["barcode"] = doc.id
            return data
        return None

    def delete_items_by_barcodes(self, barcodes: list[str]) -> int:
        """
        Delete items by a list of barcodes.

        Args:
            barcodes: List of barcodes to remove.

        Returns:
            Number of items successfully deleted.
        """
        if not barcodes:
            return 0

        deleted_count = 0

        # Firestore batch has a limit of 500 operations
        chunk_size = 450
        for i in range(0, len(barcodes), chunk_size):
            chunk = barcodes[i : i + chunk_size]
            batch = self._db.batch()

            for barcode in chunk:
                barcode = str(barcode).strip()
                doc_ref = self._collection.document(barcode)
                batch.delete(doc_ref)

            batch.commit()
            deleted_count += len(chunk)

        logger.info(f"Deleted {deleted_count} items from database")
        return deleted_count

    def delete_all_items(self) -> int:
        """
        Delete ALL items from the database. Use with caution.

        Returns:
            Number of items deleted
        """
        # Retrieving all documents
        # Note: If collection is massive (millions), this needs a different approach (recursive delete)
        # But for thousands, this is fine.
        docs = list(self._collection.list_documents())
        total_count = len(docs)

        if total_count == 0:
            return 0

        logger.info(f"Deleting all {total_count} items from database...")

        batch = self._db.batch()
        count = 0
        deleted = 0

        for doc in docs:
            batch.delete(doc)
            count += 1

            if count >= 450:
                batch.commit()
                deleted += count
                logger.info(f"Deleted {deleted}/{total_count} items")
                batch = self._db.batch()
                count = 0

        if count > 0:
            batch.commit()
            deleted += count

        logger.info(f"Finished deleting {deleted} items")
        return deleted

    def search_items(self, query: str, limit: int = 50) -> list[dict]:
        """
        Search for items by barcode or name.
        Note: Firestore has limited querying capabilities.
        This does a simple prefix match on barcode if numeric, otherwise just partial name match (inefficient on large DBs without index).

        Args:
            query: Search string
            limit: Max results

        Returns:
            List of item dicts
        """
        query = query.strip()
        if not query:
            return []

        results = []

        # 1. Try direct barcode lookup
        # Try exact match
        doc = self._collection.document(query).get()
        if doc.exists:
            data = doc.to_dict()
            data["barcode"] = doc.id
            results.append(data)

        # 2. Try simple name search (requires client-side filtering or full text search engine)
        if not results:
            # Try searching by name field logic
            # This is a very basic "starts with"
            query_end = query + "\uf8ff"
            # Use FieldFilter to avoid "positional arguments" warning in newer lib versions
            name_query = (
                self._collection.where(filter=FieldFilter("name", ">=", query))
                .where(filter=FieldFilter("name", "<=", query_end))
                .limit(limit)
                .stream()
            )

            for doc in name_query:
                data = doc.to_dict()
                data["barcode"] = doc.id
                # Avoid duplicates
                if not any(r["barcode"] == data["barcode"] for r in results):
                    results.append(data)

        return results

    def get_random_items(self, limit: int = 2) -> list[dict]:
        """
        Get a few random items to use as samples.

        Args:
            limit: Number of items to return

        Returns:
            List of item dicts
        """
        # Limiting to a small number of docs to avoid cost
        docs = list(self._collection.limit(limit).stream())
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["barcode"] = doc.id
            results.append(data)
        return results
