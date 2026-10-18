"""Immutable SQLite migration-52 restore admission metadata."""

# This list applies only when restoring a backup whose schema version includes
# migration 52.  Later migrations must declare their own historical trigger
# sets instead of changing the v52 contract.
BUDGET_52_RESTORE_ADMISSION_TRIGGERS = (
    "budget_envelope_insert_guard",
    "budget_event_insert_guard",
    "budget_event_apply",
)
