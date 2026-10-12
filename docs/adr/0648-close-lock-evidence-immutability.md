# ADR 0648: Make generic close lock evidence immutable

## Status

Accepted — 2026-08-26

## Context

The generic close-management SoD control now records the actor that locks a
period. A second race-resistant boundary is required: after a period is
locked, direct persistence changes must not replace the locker or its lock
timestamp while leaving the status as `Locked`. Otherwise the identity used by
the independent-reopen rule could be rewritten before review.

## Decision

Serialize PostgreSQL task mutations and period status mutations on the parent
close-period row with `SELECT ... FOR UPDATE`. Re-read the task after taking
that lock so dependency checks and before-state evidence describe the state
being changed. Reject a second lock of an already locked period in the
application boundary.

Add SQLite migration 45 and PostgreSQL Alembic revision
`0092_pg_close_lock_evidence` with a persistence trigger/function that refuses
changes to `locked_by` or `locked_at` while status remains `Locked`. The
PostgreSQL migration is additive; its downgrade restores the 0091 SoD guard.

## Boundary and rollback

This protects ReconForge close-workflow metadata and supported adapter
concurrency. It does not prove distributed cross-host locking, statutory
close, or source-ERP posting. SQLite rollback is a pre-migration backup
restore; PostgreSQL downgrade is the versioned 0092 downgrade and retains the
0091 SoD guard.
