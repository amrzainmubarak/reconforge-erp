# ADR 0649: Serialize consolidation-close run preparation

## Status

Accepted — 2026-08-26

## Context

Consolidation-close preparation checks the parent period before inserting a
replay-verified run. Without holding the same transaction boundary as period
locking, a stale open-period read could race with a lock and admit a new run
after the period became locked.

## Decision

PostgreSQL `prepare_run` selects the parent consolidation period with
`FOR UPDATE` before checking its state. SQLite starts `BEGIN IMMEDIATE` before
re-reading the period, resolving an existing deterministic run identity, and
inserting a new run. The worksheet and resulting control journal remain
explicitly non-posting.

## Boundary and rollback

This protects supported local and PostgreSQL adapter concurrency. It does not
provide a distributed lock service, statutory/legal-book close, source-ERP
posting, HA/DR, or production assurance. Rollback is an adapter code revert;
no schema migration is required.
