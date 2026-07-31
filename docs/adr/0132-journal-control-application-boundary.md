# ADR 0132: Journal control application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

The local journal-control service combined file ingress, exact amount handling,
policy evaluation, SQLite mutation, unified exception creation, audit, outbox,
and reporting. This prevented a backend-neutral application use case and made
transaction ownership implicit across two services.

## Decision

Define a complete `JournalControlRepositoryProtocol` covering import, policy
execution, exception reads, and reports. `JournalControlApplicationService`
depends only on that protocol. Move local behavior to
`SQLiteJournalControlRepository`, which calls the extracted SQLite exception
repository directly with autocommit disabled so journal exceptions, the unified
queue, audit, and outbox remain one transaction. Retain
`JournalControlService(connection)` as a SQL-free compatibility facade and
re-export `JournalImportResult` from its historical module.

Handled policy and SQLite failures explicitly roll back. Exact financial input,
canonical Decimal text, deterministic IDs, policies, ordering, metadata, and
return shapes remain unchanged.

## Consequences

- Application orchestration is connection-free and structurally ready for a
  PostgreSQL journal adapter.
- Existing CLI, demo, and Python callers require no migration.
- PostgreSQL semantics, RLS, live parity, and scale remain unproven.
- Rollback restores the previous service implementation; persisted schemas and
  data require no migration.
