# Firestore Maintenance Guide

This project now has three Firestore maintenance scripts:

- `scripts/firestore_audit.py`
- `scripts/cleanup_firestore_collections.py`
- `scripts/migrate_orders_legacy_fields.py`

## 1) Audit current DB structure

Generate live inventory reports:

```bash
uv run python scripts/firestore_audit.py --project-id super-home-automation
```

Outputs:
- `docs/firestore-audit.json`
- `docs/firestore-audit.md`

Notes:
- `processed_messages` + `processed_order_events` coexistence is intentional in this codebase:
  - `processed_messages`: ingestion lock by Gmail `message_id`
  - `processed_order_events`: processor lock by `event_id`

## 2) Clean legacy root collections

Dry-run first:

```bash
uv run python scripts/cleanup_firestore_collections.py
```

Execute delete:

```bash
uv run python scripts/cleanup_firestore_collections.py --execute --yes
```

Defaults target:
- `products`
- `health_check`

Override target collections:

```bash
uv run python scripts/cleanup_firestore_collections.py --collections products health_check
```

## 3) Migrate legacy fields from `orders`

Targets:
- top-level: `date`, `vat_rate`
- nested: `line_items[].vat_status`

Dry-run first:

```bash
uv run python scripts/migrate_orders_legacy_fields.py
```

Execute migration:

```bash
uv run python scripts/migrate_orders_legacy_fields.py --execute --yes
```

## Recommended operational flow

1. Run audit.
2. Run cleanup/migration dry-runs.
3. Run execute mode.
4. Re-run audit to verify final state.
