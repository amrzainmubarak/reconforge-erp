# ADR 0144: Extract governed purchase-to-pay as one application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Supplier, purchase-order, receipt, supplier-invoice, lifecycle, and three-way
match behavior was implemented directly in a SQLite-bound Platform service.
These use cases share exact quantity, minor-unit, currency, idempotency,
optimistic-version, maker/checker, exception, audit, and outbox invariants.

## Decision

Define one typed, connection-free Application protocol covering all 15 public
use cases. Move the existing implementation to `SQLitePayablesRepository`, and
retain `PayablesService(connection)` as a SQL-free compatibility facade. Move
the three public immutable input/result types to Application and re-export them
from Platform.

Amounts remain integer minor units and quantities remain canonical decimal
text across the port. SQLite continues to own validation, lifecycle, SoD,
idempotency replay, three-way matching, unified exceptions, transactions,
audit, and outbox effects. Fault injection and approval-surface inventories
target the adapter that now owns those effects.

## Consequences

- Application imports neither SQLite nor Infrastructure.
- Existing API and direct Python callers retain constructor, methods, types,
  defaults, and response shapes.
- The repository inventory falls to two direct-SQLite services.
- PostgreSQL payables parity is not established by this extraction.

## Rollback

No schema or stored data changed. The facade can be redirected without data
migration. Restoring float money, partial financial effects, weaker SoD, or
non-deterministic matching is not an acceptable rollback.
