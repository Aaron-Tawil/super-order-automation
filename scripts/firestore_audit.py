#!/usr/bin/env python3
"""
Firestore structural audit utility.

Generates:
- JSON inventory with discovered collections, field usage, and sample documents.
- Markdown report with findings, unknown collections, and legacy/unused candidates.

Usage:
  uv run python scripts/firestore_audit.py
  uv run python scripts/firestore_audit.py --project-id super-home-automation --max-docs 300
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import firestore

from src.shared.config import settings
from src.shared.models import ExtractedOrder, LineItem


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


@dataclass
class ScanConfig:
    max_docs_per_collection: int
    sample_docs_per_collection: int
    max_depth: int


ROOT_COLLECTION_EXPECTED = {
    settings.FIRESTORE_ORDERS_COLLECTION,
    settings.FIRESTORE_SESSIONS_COLLECTION,
    settings.FIRESTORE_PROCESSING_COLLECTION,
    settings.FIRESTORE_EMAIL_OUTBOX_COLLECTION,
    "items",
    "suppliers",
    "processed_messages",
    "processed_order_events",
}

# In this project these two collections are intentionally separate:
# - processed_messages: ingestion-level idempotency (Gmail message_id key)
# - processed_order_events: processor-level idempotency (event_id key)
INTENTIONAL_COEXISTING_COLLECTIONS: set[frozenset[str]] = {frozenset({"processed_messages", "processed_order_events"})}


def collection_path(col_ref: firestore.CollectionReference) -> str:
    """
    Return a stable collection path across Firestore client versions.
    """
    if hasattr(col_ref, "path"):
        return str(col_ref.path)

    raw_path = getattr(col_ref, "_path", None)
    if raw_path is None:
        return col_ref.id

    if isinstance(raw_path, (list, tuple)):
        return "/".join(str(part) for part in raw_path)

    return str(raw_path)


def build_expected_fields() -> dict[str, set[str]]:
    order_fields = set(ExtractedOrder.model_fields.keys())
    order_fields.update({"created_at", "gcs_uri", "status"})

    line_item_fields = set(LineItem.model_fields.keys())

    return {
        "orders": order_fields,
        "orders.line_items[]": line_item_fields,
        "sessions": {"order", "metadata", "created_at", "expires_at"},
        "processing_events": {"event_id", "status", "stage", "updated_at", "created_at", "details"},
        "email_outbox": {
            "event_id",
            "email_type",
            "status",
            "thread_id",
            "message_id",
            "to",
            "subject",
            "body",
            "is_html",
            "attachment_refs",
            "order_ids",
            "failed_order_id",
            "attempt_count",
            "max_attempts",
            "next_attempt_at",
            "created_at",
            "updated_at",
            "sent_at",
            "last_error",
        },
        "items": {"item_code", "name", "note"},
        "suppliers": {
            "name",
            "global_id",
            "email",
            "additional_emails",
            "phone",
            "special_instructions",
            "created_at",
            "updated_at",
            "last_modified",
            "updated_by",
        },
        "processed_messages": {
            "status",
            "created_at",
            "expires_at",
            "processed_at",
            "attempt_count",
            "error_message",
        },
        "processed_order_events": {
            "status",
            "created_at",
            "expires_at",
            "processed_at",
            "attempt_count",
            "error_message",
        },
    }


def collection_count(col_ref: firestore.CollectionReference) -> int | None:
    try:
        agg = col_ref.count().get()
        return int(agg[0][0].value)
    except Exception:
        return None


def normalize_field_stats(field_type_counts: dict[str, Counter]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for field_name, counts in field_type_counts.items():
        out[field_name] = dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    return dict(sorted(out.items(), key=lambda x: x[0]))


def scan_collection(
    col_ref: firestore.CollectionReference,
    config: ScanConfig,
    depth: int,
    expected_fields_map: dict[str, set[str]],
) -> dict[str, Any]:
    count = collection_count(col_ref)

    docs_iter = col_ref.limit(config.max_docs_per_collection).stream()
    scanned_docs = []
    for doc in docs_iter:
        scanned_docs.append(doc)

    field_types: dict[str, Counter] = defaultdict(Counter)
    sample_docs: list[dict[str, Any]] = []
    discovered_subcollections: set[str] = set()

    for i, doc in enumerate(scanned_docs):
        data = doc.to_dict() or {}

        for key, value in data.items():
            field_types[key][value_type(value)] += 1

        if i < config.sample_docs_per_collection:
            sample_docs.append(
                {
                    "id": doc.id,
                    "field_count": len(data),
                    "fields": sorted(data.keys()),
                }
            )

        if depth < config.max_depth:
            try:
                for sub in doc.reference.collections():
                    discovered_subcollections.add(sub.id)
            except Exception:
                pass

    field_stats = normalize_field_stats(field_types)
    fields_seen = set(field_stats.keys())

    coll_id = col_ref.id
    expected_fields = expected_fields_map.get(coll_id, set())
    extra_fields = sorted(fields_seen - expected_fields) if expected_fields else []
    missing_fields = sorted(expected_fields - fields_seen) if expected_fields else []

    line_item_extra_fields: list[str] = []
    if coll_id == "orders":
        expected_line_item_fields = expected_fields_map.get("orders.line_items[]", set())
        found_line_item_fields: set[str] = set()

        for doc in scanned_docs:
            data = doc.to_dict() or {}
            items = data.get("line_items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        found_line_item_fields.update(item.keys())

        if expected_line_item_fields:
            line_item_extra_fields = sorted(found_line_item_fields - expected_line_item_fields)

    return {
        "collection_id": coll_id,
        "collection_path": collection_path(col_ref),
        "depth": depth,
        "doc_count": count,
        "scanned_docs": len(scanned_docs),
        "fully_scanned": bool(count is not None and count <= config.max_docs_per_collection),
        "field_stats": field_stats,
        "sample_docs": sample_docs,
        "subcollections_seen": sorted(discovered_subcollections),
        "extra_fields_vs_expected": extra_fields,
        "missing_fields_vs_expected": missing_fields,
        "line_item_extra_fields_vs_expected": line_item_extra_fields,
    }


def build_markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Firestore Audit Report")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Project: `{report['project_id']}`")
    lines.append(f"- Max docs scanned per collection: `{report['scan_config']['max_docs_per_collection']}`")
    lines.append(f"- Max recursion depth: `{report['scan_config']['max_depth']}`")
    lines.append("")

    root = report["root_collections"]
    lines.append("## Root Collections")
    lines.append(f"- Found: `{', '.join(root['found']) if root['found'] else '(none)'}`")
    lines.append(f"- Unknown (not referenced in code): `{', '.join(root['unknown']) if root['unknown'] else '(none)'}`")
    lines.append(f"- Missing expected: `{', '.join(root['missing']) if root['missing'] else '(none)'}`")
    lines.append("")

    lines.append("## Collection Details")
    for coll in report["collections"]:
        lines.append(f"### `{coll['collection_path']}`")
        lines.append(f"- Estimated doc count: `{coll['doc_count']}`")
        lines.append(f"- Scanned docs: `{coll['scanned_docs']}`")
        lines.append(f"- Fully scanned: `{coll['fully_scanned']}`")
        lines.append(
            f"- Subcollections seen: `{', '.join(coll['subcollections_seen']) if coll['subcollections_seen'] else '(none)'}`"
        )

        if coll["extra_fields_vs_expected"]:
            lines.append(f"- Extra fields vs expected: `{', '.join(coll['extra_fields_vs_expected'])}`")
        if coll["missing_fields_vs_expected"]:
            lines.append(f"- Missing fields vs expected: `{', '.join(coll['missing_fields_vs_expected'])}`")
        if coll["line_item_extra_fields_vs_expected"]:
            lines.append(
                f"- Extra `orders.line_items[]` fields: `{', '.join(coll['line_item_extra_fields_vs_expected'])}`"
            )

        if coll["field_stats"]:
            lines.append("- Fields and observed types:")
            for field_name, type_map in coll["field_stats"].items():
                type_summary = ", ".join(f"{t}:{n}" for t, n in type_map.items())
                lines.append(f"  - `{field_name}` -> `{type_summary}`")

        if coll["sample_docs"]:
            lines.append("- Sample documents:")
            for sample in coll["sample_docs"]:
                fields_text = ", ".join(sample["fields"])
                lines.append(f"  - `{sample['id']}` ({sample['field_count']} fields): `{fields_text}`")

        lines.append("")

    lines.append("## Obsolete / Unused Candidates")
    candidates = report["obsolete_candidates"]
    if not candidates:
        lines.append("- None detected by static rules.")
    else:
        for candidate in candidates:
            lines.append(f"- {candidate}")

    lines.append("")
    lines.append("## Notes")
    lines.append("- Unknown collections and extra fields are candidates, not guaranteed safe to delete.")
    lines.append("- Confirm usage via logs, dashboards, and retention requirements before cleanup.")

    return "\n".join(lines) + "\n"


def make_obsolete_candidates(report: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    unknown_roots = report["root_collections"]["unknown"]
    for name in unknown_roots:
        candidates.append(f"Root collection `{name}` is not referenced in repository code.")

    coll_by_id = defaultdict(list)
    for coll in report["collections"]:
        coll_by_id[coll["collection_id"]].append(coll)

    present_collections = set(coll_by_id.keys())
    for pair in INTENTIONAL_COEXISTING_COLLECTIONS:
        if pair.issubset(present_collections):
            # Known intentional overlap for this codebase.
            pass

    for coll in report["collections"]:
        if coll["extra_fields_vs_expected"]:
            extras = ", ".join(coll["extra_fields_vs_expected"])
            candidates.append(
                f"Collection `{coll['collection_path']}` has fields not in current model/service contract: {extras}."
            )

    return candidates


def run_audit(project_id: str, config: ScanConfig) -> dict[str, Any]:
    db = firestore.Client(project=project_id)
    expected_fields = build_expected_fields()

    root_collection_refs = list(db.collections())
    root_names = sorted(col.id for col in root_collection_refs)

    unknown_roots = sorted(set(root_names) - ROOT_COLLECTION_EXPECTED)
    missing_expected = sorted(ROOT_COLLECTION_EXPECTED - set(root_names))

    queue: list[tuple[firestore.CollectionReference, int]] = [(col_ref, 0) for col_ref in root_collection_refs]
    scanned_paths: set[str] = set()
    collection_reports: list[dict[str, Any]] = []

    while queue:
        col_ref, depth = queue.pop(0)
        col_path = collection_path(col_ref)
        if col_path in scanned_paths:
            continue
        scanned_paths.add(col_path)

        coll_report = scan_collection(col_ref, config, depth, expected_fields)
        collection_reports.append(coll_report)

        if depth >= config.max_depth:
            continue

        docs_iter = col_ref.limit(config.max_docs_per_collection).stream()
        for doc in docs_iter:
            try:
                for sub_ref in doc.reference.collections():
                    if collection_path(sub_ref) not in scanned_paths:
                        queue.append((sub_ref, depth + 1))
            except Exception:
                continue

    collection_reports.sort(key=lambda c: c["collection_path"])

    report = {
        "generated_at": now_utc_iso(),
        "project_id": project_id,
        "scan_config": {
            "max_docs_per_collection": config.max_docs_per_collection,
            "sample_docs_per_collection": config.sample_docs_per_collection,
            "max_depth": config.max_depth,
        },
        "root_collections": {
            "found": root_names,
            "unknown": unknown_roots,
            "missing": missing_expected,
        },
        "collections": collection_reports,
    }

    report["obsolete_candidates"] = make_obsolete_candidates(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Firestore structure and write JSON/Markdown reports")
    parser.add_argument("--project-id", default=settings.PROJECT_ID)
    parser.add_argument("--max-docs", type=int, default=250, help="Max docs scanned per collection")
    parser.add_argument("--sample-docs", type=int, default=10, help="Max sample docs listed per collection")
    parser.add_argument("--max-depth", type=int, default=3, help="Subcollection recursion depth")
    parser.add_argument("--output-json", default="docs/firestore-audit.json")
    parser.add_argument("--output-md", default="docs/firestore-audit.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = ScanConfig(
        max_docs_per_collection=args.max_docs,
        sample_docs_per_collection=args.sample_docs,
        max_depth=args.max_depth,
    )

    report = run_audit(args.project_id, cfg)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    output_md.write_text(build_markdown_report(report), encoding="utf-8")

    print(f"Wrote JSON report: {output_json}")
    print(f"Wrote Markdown report: {output_md}")


if __name__ == "__main__":
    main()
