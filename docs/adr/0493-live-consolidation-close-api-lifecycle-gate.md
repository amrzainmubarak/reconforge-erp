# ADR 0493: Live Alembic-head consolidation-close lifecycle gate

- **Date:** 2026-08-10
- **Status:** Accepted

## Decision

Add an authenticated PostgreSQL server-boundary gate for the complete
consolidation-close lifecycle. The disposable PostgreSQL 16 runtime starts
empty, runs Alembic through head `0086_pg_close_reopened`, grants only the
required tables to a non-superuser/non-`BYPASSRLS` role, and exercises period
creation/replay, worksheet preparation, maker-checker approval/posting,
reversal, lock/reopen, run detail replay, and tenant/workspace denial.

Align PostgreSQL period state with the existing API and SQLite contract by
persisting `Reopened` explicitly. The additive `0086_pg_close_reopened`
migration refuses downgrade while reopened rows exist; locking accepts both
`Open` and `Reopened` periods.

## Rationale

Earlier PostgreSQL close evidence covered direct schema setup and read or
partial lifecycle paths. A migration-head authenticated lifecycle test is the
smallest reproducible proof that the real authorization, RLS, replay, journal
effects, and maker-checker transitions work together. The state alignment
removes a backend-visible semantic mismatch rather than weakening the gate.

## Boundaries

- Synthetic single-node data and one disposable database only.
- This is a control-journal/evidence lifecycle, not statutory consolidation,
  legal-book posting, ERP/bank provider integration, write-back, HA/DR,
  restore, RPO/RTO, or production-readiness evidence.
- No GitHub publication or hosted verification is implied by the local gate.

## Verification

`tests/test_api_server_consolidation_close.py` passes the authenticated
Alembic-head HTTP lifecycle with a non-superuser/non-`BYPASSRLS` role. The
PostgreSQL close adapter suite and existing server close API suite also pass.

## Rollback

Revert the additive test, adapter change, migration, and documentation. The
migration downgrade is guarded against discarding `Reopened` state, and the
disposable runtime is removed after verification.
