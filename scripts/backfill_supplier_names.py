"""
One-time migration: backfill supplier_name in orders collection.

For every order where supplier_name is empty/Unknown but supplier_code is valid,
look up the name from the suppliers collection and write it back.
"""

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from src.data.supplier_service import SupplierService  # noqa: E402
from src.shared.config import settings  # noqa: E402
from src.shared.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

from google.cloud import firestore  # noqa: E402


def backfill_supplier_names(dry_run: bool = True) -> None:
    db = firestore.Client(project=settings.PROJECT_ID)
    orders_col = db.collection(settings.FIRESTORE_ORDERS_COLLECTION)

    # Load supplier name map once
    supplier_service = SupplierService(firestore_client=db)
    all_suppliers = supplier_service.get_all_suppliers()
    name_map: dict[str, str] = {s["code"]: s["name"] for s in all_suppliers if s.get("code") and s.get("name")}
    logger.info(f"Loaded {len(name_map)} supplier names from suppliers collection.")

    docs = list(orders_col.stream())
    logger.info(f"Scanning {len(docs)} orders...")

    updated = 0
    skipped = 0
    unchanged = 0

    for doc in docs:
        data = doc.to_dict() or {}
        supplier_code = str(data.get("supplier_code") or "").strip()
        supplier_name = str(data.get("supplier_name") or "").strip()

        # Skip if no valid code or already has a real name
        if not supplier_code or supplier_code.upper() in ("UNKNOWN", ""):
            skipped += 1
            continue

        if supplier_name and supplier_name.upper() not in ("UNKNOWN", ""):
            unchanged += 1
            continue

        # Look up name from suppliers
        correct_name = name_map.get(supplier_code)
        if not correct_name:
            logger.warning(f"  [{doc.id}] supplier_code={supplier_code} not found in suppliers collection.")
            skipped += 1
            continue

        logger.info(f"  [{doc.id}] '{supplier_name}' → '{correct_name}' (code: {supplier_code})")

        if not dry_run:
            doc.reference.update({"supplier_name": correct_name})

        updated += 1

    print("\n" + "=" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}Migration complete.")
    print(f"  Updated : {updated}")
    print(f"  Already correct (unchanged): {unchanged}")
    print(f"  Skipped (no code or not in suppliers): {skipped}")
    if dry_run:
        print("\nRun with --apply to actually write changes.")
    print("=" * 60)


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    if not dry:
        print("⚠️  APPLY MODE — writing to Firestore...")
    else:
        print("ℹ️  DRY RUN — no changes will be written. Pass --apply to commit.")
    backfill_supplier_names(dry_run=dry)
