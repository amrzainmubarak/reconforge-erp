# ADR 0159: PostgreSQL inventory valuation reversal aggregate

## Status

Accepted — 2026-07-28

## Context

Approved FIFO valuations and their Finance Drafts are immutable. Correction
therefore requires a separately Posted exact-opposite inventory movement and a
new governed reversal record; changing or deleting the original evidence would
destroy financial lineage. PostgreSQL valuation parity cannot be complete while
this compensating path exists only in SQLite.

## Decision

Add migration 0026 with tenant-qualified reversal and layer-effect tables under
forced RLS. A Draft reversal binds one Approved valuation to one separately
Posted mirror movement. Approval must be maker-checker and atomic: persist one
exact effect for every original inbound layer or outbound consumption, update
locked layers to their equation-derived balances, create a new balanced Finance
Draft by swapping every original debit and credit, then finalize the reversal.

Layer balances are governed by `original - consumptions + restores - removes`.
Approved reversal effects, dependent Finance evidence, and the compensating
movement are immutable. Cancellation is Draft-only. Downgrade removes reversal
dependencies child-first and restores the migration-0025 layer guard.

## Consequences

No approved history is rewritten, no Finance entry is automatically validated,
and no external ERP write occurs. PostgreSQL parity remains absent until all
seven application operations plus a non-superuser lifecycle/RLS test exist and
the locked gates pass.
