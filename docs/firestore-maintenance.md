# Firestore Maintenance Guide

The only Firestore maintenance script currently kept in this repository is:

- `scripts/firestore_audit.py`

## Audit current DB structure

Generate a live inventory report:

```bash
uv run python scripts/firestore_audit.py --project-id super-home-automation
```

Outputs:
- `docs/firestore-audit.json`
- `docs/firestore-audit.md`

Notes:
- `processed_messages` and `processed_order_events` coexist intentionally.
- `processed_messages` is the ingestion lock keyed by Gmail `message_id`.
- `processed_order_events` is the processor lock keyed by `event_id`.

## Recommended operational flow

1. Run the audit script.
2. Review the generated Markdown and JSON reports.
3. Decide any manual cleanup or one-off migration from the report output.
4. Re-run the audit after changes to verify the final state.
