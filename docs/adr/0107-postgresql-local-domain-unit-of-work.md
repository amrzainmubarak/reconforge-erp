# ADR-0107: PostgreSQL local-domain unit of work

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-001, P1-PLAT-002

## Decision

Implement the existing workspace/initial-period Application contract on
PostgreSQL through a tenant-bound unit of work. One connection and transaction
own the workspace, period, both audit events, and audit-ledger head. PostgreSQL
RLS is forced on all four tables; audit events are append-only; the ledger head
is row-locked so concurrent appends remain contiguous. Both adapters call the
same pure canonical hash function rather than duplicating chain logic.

The tables use a `domain_` prefix because they are a compatibility persistence
adapter for the current local-first `Workspace` and `Period` models. They are
not declared equivalent to the enterprise Organization/FiscalPeriod model and
do not replace the later canonical-model migration.

## Consequences

- The Application service remains free of SQLite/PostgreSQL imports.
- SQLite and PostgreSQL produce the same business fields, actions, and metadata
  shape; generated IDs, timestamps, and therefore hashes intentionally differ.
- A failure on the second audit append rolls back every row and the chain head.
- The migration supports downgrade and re-upgrade; other Platform services
  still coupled to SQLite remain explicit backlog work.
