# ADR-0106: PostgreSQL durable-job contract parity

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-002

## Decision

Implement the durable-job Application ports with a tenant-scoped PostgreSQL
adapter whose public operations each own a transaction. Use database RLS,
optimistic aggregate versions, atomic scoped idempotency, `FOR UPDATE SKIP
LOCKED` claims, expiring generation-fenced leases, and append-only transition,
lease, and partition-effect evidence.

The same partition effect and its checkpoint or final manifest commit in one
transaction. A resumed worker enumerates committed effects before continuing;
an expired generation cannot write. PostgreSQL migrations must prove forward,
downgrade, and re-upgrade behavior on a new database.

## Consequences

- SQLite remains the zero-network Community adapter.
- PostgreSQL 17 live tests compare the same two-partition semantic output with
  SQLite and exercise real connection loss and lease takeover.
- Concurrent identical submissions resolve to one creation and one replay.
- This is parity for the durable-job boundary, not every existing Platform
  service; P1-PLAT-002 remains in progress.
