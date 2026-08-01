# ADR 0160: PostgreSQL inventory planning and count aggregate

## Status

Accepted — 2026-07-28

## Context

Inventory counts compare a point-in-time Posted stock snapshot with human-entered
quantities. Approval can create financially relevant inventory movement input;
silently accepting a stale snapshot or a mismatched adjustment would corrupt
subsequent valuation and reconciliation. Reorder signals are advisory and must
not create purchase orders or perform external writeback.

## Decision

Add migration 0027 with tenant-qualified count-session, immutable count-line,
and reorder-rule tables under forced RLS. Starting a count freezes all non-zero
Posted balances at one location. Count results are editable only while Counting,
submission requires every line, and approval requires a distinct checker.

Approval must re-read and lock current stock, reject any change since snapshot,
and create at most one Draft Adjustment. Database guards independently require
that every variance has exactly one matching adjustment line with the same item,
UOM, lot, precision, absolute quantity, and correct location direction; no
adjustment is allowed for a zero-variance count. The adjustment remains Draft
and can be posted through the existing maker-checker movement workflow.

Reorder rules use exact scaled quantities and produce deterministic advisory
signals from Posted local on-hand only. They do not represent open supply,
purchasing commitments, forecasts, or ERP writeback.

## Consequences

The slice preserves local-first behavior and audit lineage without automatic
financial posting. PostgreSQL parity remains absent until all thirteen protocol
operations, a non-superuser lifecycle/RLS test, and locked gates pass.
