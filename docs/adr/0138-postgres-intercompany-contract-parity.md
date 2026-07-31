# ADR 0138: PostgreSQL intercompany contract parity

- Status: Accepted
- Date: 2026-07-28

## Context

The extracted intercompany application boundary preserves exact imports,
deterministic reference grouping, imbalance cases, unified exceptions,
settlement, audit, and outbox effects on SQLite. The optional server profile
must preserve the complete effect boundary under tenant isolation without
reintroducing binary floating-point amounts or orphan settlement evidence.

## Decision

Implement all five application-port methods in a tenant-bound PostgreSQL
repository. Migration 0018 adds tenant-keyed transaction and case tables using
`NUMERIC` plus canonical decimal text, composite workspace foreign keys, and
forced RLS. Every operation establishes transaction-local tenant scope.

Import and match effects include their audit and outbox records in the same
transaction. Imbalance cases reuse the shared control-exception queue. A
settlement must update exactly one tenant-scoped case before it may append audit
or outbox evidence. Matching retains stable period/reference/entity/transaction
ordering and exact `Decimal` aggregation.

## Consequences

The application contract now has SQLite and PostgreSQL adapters plus an
additive migration and optional live non-superuser parity test. Local tests
prove rejection before transaction start, rollback before and after writes,
and the absence of settlement evidence for a missing case.

Live RLS and backend runtime parity are not claimed until the optional test runs
against a configured non-owner application role. Downgrade removes only the two
new tables and leaves the SQLite contract and shared exception queue unchanged.
