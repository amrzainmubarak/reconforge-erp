# ADR 0024: PostgreSQL Close-Control Boundary

- Status: Accepted as a bounded server slice
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The authenticated PostgreSQL profile had tenant identity, master data, ledger
control, and audit reads, but close management still read the legacy local
SQLite service. A server-side close workflow needs tenant-scoped persistence,
readiness and dependency rules, and auditable transitions without pretending
to control a source ERP's statutory posting period.

## Decision

Add Alembic revision `0006_postgres_close` and
`PostgresCloseRepository`. The schema stores close-control periods, tasks, and
task dependencies with composite tenant foreign keys, deterministic indexes,
forced RLS, and explicit status checks. A close period references an existing
PostgreSQL fiscal period and organization. The server API creates five
deterministic starter tasks, computes readiness, blocks task completion when a
dependency is incomplete, requires full readiness before approval or locking,
and requires a reason to reopen.

Every server mutation appends a tenant-scoped audit-chain event and
transactional outbox record in the caller-owned transaction. The adapter never
falls back to SQLite. A close-control `Locked` state is application metadata
only and does not lock source-ERP postings.

## Consequences

- Close coordination is now persisted in PostgreSQL for the supported server
  profile and remains isolated by tenant.
- The local SQLite close service and CLI remain unchanged.
- Dependencies, notifications, delegated ownership, approval limits, and
  broader close evidence binders remain future slices.
- The feature is not statutory close, a legal certification, a digital
  signature, or an ERP write-back integration.

## Rejected alternatives

- Reusing the SQLite close tables in server mode: this would create a hidden
  persistence fallback and make server scope difficult to prove.
- Treating fiscal-period metadata status as a source-ERP lock: the application
  cannot claim a posting lock without an explicit ERP integration contract.
