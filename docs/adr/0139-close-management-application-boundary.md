# ADR 0139: Close-management application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Local close periods, task dependencies, readiness mutation, lock/reopen, and
audit evidence were implemented directly in a connection-bound Platform
service. Dependency edges could form cycles. Reopening an unknown period could
commit an audit event before the final read reported that the period was absent.

## Decision

Define one backend-neutral repository protocol covering all 11 public methods,
including the historical audit/autocommit controls required by nested period
initialization. Move SQLite behavior into an infrastructure adapter and retain
the Platform constructor as a compatibility facade.

Keep readiness as exact `Decimal`. Before inserting a dependency, reject self-
edges and use a recursive query to determine whether the target already reaches
the source. Before reopen evidence, validate the period and require exactly one
updated row. Roll back handled reopen failures.

## Consequences

The application layer is connection-free, cyclic close graphs fail closed, and
the audit ledger cannot claim a missing period was reopened. Existing local
callers, schemas, IDs, statuses, and readiness values remain compatible.

The route-oriented PostgreSQL close repository predates this port and remains a
separate contract. Converging it, proving live parity, and adding concurrent
status fencing are later gates.
