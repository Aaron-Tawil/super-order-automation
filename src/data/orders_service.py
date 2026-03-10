"""
Orders service for dashboard listing and lookup.
"""

from datetime import UTC, datetime

from google.cloud import firestore

from src.shared.config import settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class OrdersService:
    """Service for reading persisted orders from Firestore."""

    def __init__(self, firestore_client: firestore.Client | None = None):
        self._db = firestore_client or firestore.Client(project=settings.PROJECT_ID)
        self._collection = self._db.collection(settings.FIRESTORE_ORDERS_COLLECTION)

    def list_orders(self, limit: int = 500) -> list[dict]:
        """
        Return newest orders first.
        """
        docs = self._collection.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit).stream()
        results: list[dict] = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["order_id"] = doc.id
            # Legacy docs may miss this field; default to real order.
            data["is_test"] = bool(data.get("is_test", False))
            results.append(data)
        return results

    def get_order(self, order_id: str) -> dict | None:
        """
        Return a single order document by id.
        """
        if not order_id:
            return None

        doc = self._collection.document(str(order_id)).get()
        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        data["order_id"] = doc.id
        data["is_test"] = bool(data.get("is_test", False))

        # Guard against corrupted timestamps in edge cases.
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                data["created_at"] = datetime.fromisoformat(created_at)
            except ValueError:
                pass

        return data

    def find_order_id_by_session(self, session_id: str) -> str | None:
        """
        Resolve an order id by stored session id.
        """
        if not session_id:
            return None

        docs = self._collection.where("session_id", "==", str(session_id)).limit(1).stream()
        for doc in docs:
            return doc.id
        return None

    def update_order_test_flag(self, order_id: str, is_test: bool) -> bool:
        """
        Update persisted order classification (real/test).
        """
        if not order_id:
            return False

        try:
            doc_ref = self._collection.document(str(order_id))
            if not doc_ref.get().exists:
                return False
            doc_ref.update({"is_test": bool(is_test), "updated_at": _utc_now()})
            return True
        except Exception as e:
            logger.error(f"Failed updating is_test for order {order_id}: {e}")
            return False

    def update_order_test_flags(self, updates: dict[str, bool]) -> tuple[int, int]:
        """
        Bulk update order test flags.
        Returns (updated_count, failed_count).
        """
        if not updates:
            return 0, 0

        updated = 0
        failed = 0
        for order_id, is_test in updates.items():
            if self.update_order_test_flag(order_id=order_id, is_test=is_test):
                updated += 1
            else:
                failed += 1
        return updated, failed

    def update_order_data(self, order_id: str, new_order_data: dict) -> bool:
        """
        Overwrite the order with new data (e.g. from a manual extraction retry).
        """
        if not order_id or not new_order_data:
            return False

        try:
            doc_ref = self._collection.document(str(order_id))
            if not doc_ref.get().exists:
                return False
            
            new_order_data["updated_at"] = _utc_now()
            doc_ref.update(new_order_data)
            return True
        except Exception as e:
            logger.error(f"Failed updating order data for {order_id}: {e}")
            return False
