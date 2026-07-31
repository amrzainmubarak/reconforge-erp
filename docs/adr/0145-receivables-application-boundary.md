# ADR 0145: Extract governed accounts receivable as one application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Customer credit, sales invoice, receipt, allocation, exposure, and aging
behavior was implemented directly in a SQLite-bound Platform service. These
use cases share minor-unit, exact-quantity, currency, credit, idempotency,
optimistic-version, maker/checker, allocation, audit, and outbox invariants.

## Decision

Define one typed, connection-free Application protocol covering all 13 public
use cases. Move the implementation to `SQLiteReceivablesRepository`, retain
`ReceivablesService(connection)` as a SQL-free compatibility facade, and move
the immutable invoice-line and allocation inputs to Application while
re-exporting them from Platform.

Amounts and limits remain integer minor units and quantities remain canonical
decimal text. SQLite continues to own validation, credit checks and overrides,
lifecycle, SoD, idempotency, allocations, exposure/aging queries,
transactions, audit, and outbox effects. Governance inventories reference the
adapter that owns approval and persisted JSON processing.

## Consequences

- Application imports neither SQLite nor Infrastructure.
- API, CLI, backup, and direct Python callers retain their public contract.
- Matching becomes the only remaining direct-SQLite Platform service.
- PostgreSQL receivables parity is not established by this extraction.

## Rollback

No schema or stored data changed. The facade can be redirected without data
migration. Restoring float money, partial allocations, weaker SoD/credit
controls, or non-deterministic aging is not an acceptable rollback.
